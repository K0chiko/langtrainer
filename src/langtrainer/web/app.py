import shutil
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session as DBSession
from sqlmodel import select

from ..config import settings
from .. import advisor, cards, i18n, session_ops, stats, storage
from .. import progress as job_progress  # имя `progress` занято функцией страницы /progress
from ..db import get_db, get_engine, init_db
from ..models import Error, Learner, Participant, Session, SessionProgress, Utterance
from ..pipeline import run_analysis, run_session
from ..recording import RecorderError, recorder

def _i18n_context(request: Request) -> dict:
    lang = i18n.pick_language(request.cookies.get(i18n.COOKIE), request.headers.get("accept-language"))
    return {
        "lang": lang,
        "languages": i18n.LANGUAGES,
        "t": lambda key, **values: i18n.translate(lang, key, **values),
        "tv": lambda prefix, value: i18n.translate_value(lang, prefix, value),
    }


templates = Jinja2Templates(
    directory=str(Path(__file__).parent / "templates"), context_processors=[_i18n_context]
)


def _due_count() -> int:
    with DBSession(get_engine()) as db:
        learner = db.exec(select(Learner)).first()
        return cards.due_count(db, learner.id) if learner else 0


templates.env.globals["due_count"] = _due_count
# В БД время хранится в UTC, на странице показываем местное
templates.env.filters["local"] = lambda d: d.astimezone()
templates.env.filters["size"] = storage.format_size


def _startup() -> None:
    """Подготовка базы. Вызывается, когда папка данных известна: при запуске или сразу после её выбора."""
    init_db()
    with DBSession(get_engine()) as db:
        job_progress.mark_interrupted(db)  # задачи живут в процессе: после перезапуска «в обработке» = оборвано
        learner = db.exec(select(Learner)).first()
        cards.generate_cards(db, learner.id)  # карточки для ошибок, найденных до появления карточек


@asynccontextmanager
async def lifespan(_: FastAPI):
    storage.apply_saved()
    if not storage.needs_setup():
        _startup()
    yield


app = FastAPI(title="Language Trainer", lifespan=lifespan)

_SETUP_OPEN = ("/setup", "/lang/")


@app.middleware("http")
async def require_data_folder(request: Request, call_next):
    """Пока папка данных не выбрана, всё ведёт на экран выбора."""
    if storage.needs_setup() and not request.url.path.startswith(_SETUP_OPEN):
        return RedirectResponse("/setup", status_code=303)
    return await call_next(request)


def _save_upload(upload: UploadFile, session_id: int, name: str) -> str:
    folder = settings.audio_dir / str(session_id)
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(upload.filename or "").suffix or ".wav"
    path = folder / f"{name}{suffix}"
    with path.open("wb") as out:
        shutil.copyfileobj(upload.file, out)
    return str(path)


@app.get("/lang/{code}")
def set_language(code: str, request: Request):
    if code not in i18n.LANGUAGES:
        raise HTTPException(404)
    # Go back to the page the switch was clicked on (path only, never an external address)
    back = urlparse(request.headers.get("referer", ""))
    target = (back.path or "/") + (f"?{back.query}" if back.query else "")
    response = RedirectResponse(target if target.startswith("/") and not target.startswith("//") else "/", status_code=303)
    response.set_cookie(i18n.COOKIE, code, max_age=365 * 24 * 3600, samesite="lax")
    return response


def _setup_page(request: Request, folder: str = "", error: str = ""):
    options = storage.suggested_folders()
    return templates.TemplateResponse(
        request,
        "setup.html",
        {
            "options": options,
            "folder": folder or str(options[0][1]),
            "error": error,
            "can_browse": storage.browse_available(),
        },
    )


@app.get("/setup")
def setup_form(request: Request):
    if not storage.needs_setup():
        return RedirectResponse("/", status_code=303)
    return _setup_page(request)


@app.post("/setup")
def setup_save(request: Request, folder: str = Form("")):
    if not storage.needs_setup():
        return RedirectResponse("/", status_code=303)
    try:
        storage.choose_data_dir(folder)
    except storage.StorageError as exc:
        return _setup_page(request, folder, exc.code)
    _startup()
    return RedirectResponse("/", status_code=303)


@app.post("/setup/browse")
def setup_browse(folder: str = Form("")):
    return JSONResponse({"path": storage.browse_folder(folder)})


@app.get("/storage")
def storage_page(request: Request, db: DBSession = Depends(get_db)):
    data_dir = settings.require_data_dir()
    used = storage.usage(data_dir)
    titles = {s.id: (s.title, s.status) for s in db.exec(select(Session)).all()}
    rows = sorted(
        ((sid, titles.get(sid, ("", ""))[0], titles.get(sid, ("", ""))[1], size) for sid, size in used.per_session.items()),
        key=lambda r: -r[3],
    )
    return templates.TemplateResponse(
        request,
        "storage.html",
        {
            "folder": data_dir.resolve(),
            "source": storage.source(),
            "usage": used,
            "other_audio": max(0, used.audio - sum(used.per_session.values())),
            "rows": rows,
        },
    )


@app.post("/storage/open")
def storage_open():
    storage.open_folder(settings.require_data_dir())
    return RedirectResponse("/storage", status_code=303)


@app.post("/sessions/{session_id}/delete-audio")
def delete_audio(session_id: int, request: Request, db: DBSession = Depends(get_db)):
    if db.get(Session, session_id) is None:
        raise HTTPException(404)
    try:
        session_ops.delete_audio(db, session_id, settings.audio_dir)
    except session_ops.AudioNotDeletable:
        pass
    back = urlparse(request.headers.get("referer", "")).path
    return RedirectResponse(back if back in ("/storage", f"/sessions/{session_id}") else f"/sessions/{session_id}", status_code=303)


@app.get("/")
def index(request: Request, error: str = "", db: DBSession = Depends(get_db)):
    sessions = db.exec(select(Session).order_by(Session.created_at.desc())).all()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "sessions": sessions,
            "jobs": {s.id: job_progress.job_view(db.get(SessionProgress, s.id), s.status) for s in sessions},
            "recording_since": recorder.started_at,
            "error": error,
        },
    )


@app.post("/record/start")
def record_start():
    try:
        recorder.start()
    except RecorderError as exc:
        return RedirectResponse(f"/?{urlencode({'error': str(exc)})}", status_code=303)
    return RedirectResponse("/", status_code=303)


@app.post("/record/stop")
def record_stop(background: BackgroundTasks, db: DBSession = Depends(get_db)):
    try:
        files = recorder.stop()
    except RecorderError as exc:
        return RedirectResponse(f"/?{urlencode({'error': str(exc)})}", status_code=303)
    learner = db.exec(select(Learner)).first()
    session = Session(learner_id=learner.id, title=f"Call {datetime.now():%d.%m.%Y %H:%M}")
    db.add(session)
    db.commit()
    db.refresh(session)
    folder = settings.audio_dir / str(session.id)
    folder.mkdir(parents=True, exist_ok=True)
    for role, src, name in (("learner", files.mic, "me.wav"), ("partner", files.system, "partner.wav")):
        dest = folder / name
        shutil.move(src, dest)
        db.add(Participant(session_id=session.id, role=role, lang=learner.target_lang, audio_path=str(dest)))
    db.commit()
    background.add_task(run_session, session.id)
    return RedirectResponse(f"/sessions/{session.id}", status_code=303)


@app.post("/sessions")
def create_session(
    background: BackgroundTasks,
    title: str = Form(""),
    my_audio: UploadFile = File(...),
    partner_audio: UploadFile | None = File(None),
    db: DBSession = Depends(get_db),
):
    learner = db.exec(select(Learner)).first()
    session = Session(learner_id=learner.id, title=title.strip() or my_audio.filename or "Conversation")
    db.add(session)
    db.commit()
    db.refresh(session)

    db.add(
        Participant(
            session_id=session.id,
            role="learner",
            lang=learner.target_lang,
            audio_path=_save_upload(my_audio, session.id, "me"),
        )
    )
    if partner_audio is not None and partner_audio.filename:
        db.add(
            Participant(
                session_id=session.id,
                role="partner",
                lang=learner.target_lang,
                audio_path=_save_upload(partner_audio, session.id, "partner"),
            )
        )
    db.commit()
    background.add_task(run_session, session.id)
    return RedirectResponse(f"/sessions/{session.id}", status_code=303)


@app.get("/sessions/{session_id}")
def session_detail(session_id: int, request: Request, db: DBSession = Depends(get_db)):
    session = db.get(Session, session_id)
    if session is None:
        raise HTTPException(404)
    participants = db.exec(select(Participant).where(Participant.session_id == session_id)).all()
    roles = {p.id: p.role for p in participants}
    utterances = db.exec(
        select(Utterance).where(Utterance.session_id == session_id).order_by(Utterance.start, Utterance.id)
    ).all()
    errors = db.exec(
        select(Error).join(Utterance, Error.utterance_id == Utterance.id).where(Utterance.session_id == session_id)
    ).all()
    errors_by_utt: dict[int, list[Error]] = {}
    for e in errors:
        errors_by_utt.setdefault(e.utterance_id, []).append(e)
    return templates.TemplateResponse(
        request,
        "session.html",
        {
            "session": session,
            "job": job_progress.job_view(db.get(SessionProgress, session_id), session.status),
            "rows": [(u, roles[u.participant_id], errors_by_utt.get(u.id, [])) for u in utterances],
            "error_count": len(errors),
            "audio_bytes": storage.session_audio_bytes(settings.audio_dir, session_id),
            "has_audio": any(p.audio_path for p in participants),
        },
    )


@app.post("/sessions/{session_id}/reanalyze")
def reanalyze(session_id: int, background: BackgroundTasks):
    background.add_task(run_analysis, session_id)
    return RedirectResponse(f"/sessions/{session_id}", status_code=303)


@app.post("/sessions/{session_id}/retry")
def retry(session_id: int, background: BackgroundTasks, db: DBSession = Depends(get_db)):
    """Повтор после сбоя или остановки: продолжаем с той фазы, на которой оборвалось."""
    session = db.get(Session, session_id)
    if session is None:
        raise HTTPException(404)
    if session.status == "failed":
        row = db.get(SessionProgress, session_id)
        has_text = db.exec(select(Utterance.id).where(Utterance.session_id == session_id)).first() is not None
        transcription_unfinished = (row.phase == "transcribing") if row else not has_text
        session.status, session.status_detail = "uploaded", ""  # сразу видно в интерфейсе, двойной клик не запустит дубль
        db.add(session)
        db.commit()
        background.add_task(run_session if transcription_unfinished else run_analysis, session_id)
    return RedirectResponse(f"/sessions/{session_id}", status_code=303)


@app.post("/sessions/{session_id}/rename")
def rename(session_id: int, title: str = Form(""), db: DBSession = Depends(get_db)):
    if db.get(Session, session_id) is None:
        raise HTTPException(404)
    session_ops.rename_session(db, session_id, title)
    return RedirectResponse(f"/sessions/{session_id}", status_code=303)


@app.get("/sessions/{session_id}/delete")
def delete_confirm(session_id: int, request: Request, db: DBSession = Depends(get_db)):
    """Страница подтверждения: показывает, что именно пропадёт вместе с разговором."""
    session = db.get(Session, session_id)
    if session is None:
        raise HTTPException(404)
    return templates.TemplateResponse(
        request,
        "delete.html",
        {
            "session": session,
            "impact": session_ops.deletion_impact(db, session_id),
            "busy": session.status in job_progress.IN_PROGRESS,
        },
    )


@app.post("/sessions/{session_id}/delete")
def delete(session_id: int, db: DBSession = Depends(get_db)):
    try:
        session_ops.delete_session(db, session_id, settings.audio_dir)
    except session_ops.SessionBusy:
        return RedirectResponse(f"/sessions/{session_id}/delete", status_code=303)
    return RedirectResponse("/", status_code=303)


@app.post("/errors/{error_id}/dismiss")
def dismiss(error_id: int, db: DBSession = Depends(get_db)):
    error = db.get(Error, error_id)
    if error is None:
        raise HTTPException(404)
    error.dismissed = not error.dismissed
    db.add(error)
    db.commit()
    cards.set_suspended(db, error.id, error.dismissed)
    if not error.dismissed:
        cards.generate_cards(db, error.learner_id)
    utt = db.get(Utterance, error.utterance_id)
    return RedirectResponse(f"/sessions/{utt.session_id}", status_code=303)


@app.get("/errors")
def all_errors(request: Request, db: DBSession = Depends(get_db)):
    errors = db.exec(select(Error).where(Error.dismissed == False).order_by(Error.created_at.desc())).all()  # noqa: E712
    by_rule: dict[str, int] = {}
    for e in errors:
        by_rule[e.rule_key or e.category] = by_rule.get(e.rule_key or e.category, 0) + 1
    top = sorted(by_rule.items(), key=lambda kv: -kv[1])[:10]
    return templates.TemplateResponse(request, "errors.html", {"errors": errors, "top": top})


@app.get("/review")
def review_page(request: Request, learned: int = 0, db: DBSession = Depends(get_db)):
    learner = db.exec(select(Learner)).first()
    card = cards.next_due(db, learner.id)
    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "card": card,
            "options": cards.rating_options(card) if card else [],
            "total": cards.due_count(db, learner.id),
            "just_learned": bool(learned),
            "streak": cards.EASY_STREAK_TO_LEARN,
        },
    )


@app.post("/review/{card_id}")
def review_answer(card_id: int, rating: int = Form(...), db: DBSession = Depends(get_db)):
    if rating not in (1, 2, 3, 4) or db.get(cards.Card, card_id) is None:
        raise HTTPException(400)
    became_learned = cards.review(db, card_id, rating)
    return RedirectResponse("/review?learned=1" if became_learned else "/review", status_code=303)


@app.post("/cards/{card_id}/unlearn")
def unlearn_card(card_id: int, db: DBSession = Depends(get_db)):
    cards.unlearn(db, card_id)
    return RedirectResponse("/progress", status_code=303)


_advice_running = False


def _advice_job(learner_id: int) -> None:
    global _advice_running
    _advice_running = True
    try:
        with DBSession(get_engine()) as db:
            advisor.generate_advice(db, learner_id)
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        _advice_error[0] = f"{type(exc).__name__}: {exc}"
    finally:
        _advice_running = False


_advice_error = [""]


@app.get("/progress")
def progress(request: Request, db: DBSession = Depends(get_db)):
    learner = db.exec(select(Learner)).first()
    series = stats.session_series(db, learner.id)
    return templates.TemplateResponse(
        request,
        "progress.html",
        {
            "spots": stats.weak_spots(db, learner.id, limit=8),
            "categories": stats.category_counts(db, learner.id),
            "series": series,
            "series_max": max((p.per100 for p in series), default=0) or 1,
            "reviews": stats.review_stats(db, learner.id),
            "learned_cards": cards.learned_cards(db, learner.id),
            "advice": advisor.latest_advice(db, learner.id),
            "advice_running": _advice_running,
            "advice_error": _advice_error[0],
            "recent_days": stats.RECENT_DAYS,
        },
    )


@app.post("/progress/advice")
def progress_advice(background: BackgroundTasks, db: DBSession = Depends(get_db)):
    if not _advice_running:
        _advice_error[0] = ""
        learner = db.exec(select(Learner)).first()
        background.add_task(_advice_job, learner.id)
    return RedirectResponse("/progress", status_code=303)
