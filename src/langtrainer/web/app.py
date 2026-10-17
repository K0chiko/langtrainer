import shutil
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session as DBSession
from sqlmodel import select

from ..config import settings
from .. import advisor, cards, stats
from ..db import get_db, get_engine, init_db
from ..models import Error, Learner, Participant, Session, Utterance
from ..pipeline import run_analysis, run_session
from ..recording import RecorderError, recorder

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _due_count() -> int:
    with DBSession(get_engine()) as db:
        learner = db.exec(select(Learner)).first()
        return cards.due_count(db, learner.id) if learner else 0


templates.env.globals["due_count"] = _due_count
# В БД время хранится в UTC, на странице показываем местное
templates.env.filters["local"] = lambda d: d.astimezone()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with DBSession(get_engine()) as db:  # карточки для ошибок, найденных до появления карточек
        learner = db.exec(select(Learner)).first()
        cards.generate_cards(db, learner.id)
    yield


app = FastAPI(title="Language Trainer", lifespan=lifespan)


def _save_upload(upload: UploadFile, session_id: int, name: str) -> str:
    folder = settings.audio_dir / str(session_id)
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(upload.filename or "").suffix or ".wav"
    path = folder / f"{name}{suffix}"
    with path.open("wb") as out:
        shutil.copyfileobj(upload.file, out)
    return str(path)


@app.get("/")
def index(request: Request, error: str = "", db: DBSession = Depends(get_db)):
    sessions = db.exec(select(Session).order_by(Session.created_at.desc())).all()
    return templates.TemplateResponse(
        request,
        "index.html",
        {"sessions": sessions, "recording_since": recorder.started_at, "error": error},
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
    roles = {p.id: p.role for p in db.exec(select(Participant).where(Participant.session_id == session_id))}
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
            "rows": [(u, roles[u.participant_id], errors_by_utt.get(u.id, [])) for u in utterances],
            "error_count": len(errors),
        },
    )


@app.post("/sessions/{session_id}/reanalyze")
def reanalyze(session_id: int, background: BackgroundTasks):
    background.add_task(run_analysis, session_id)
    return RedirectResponse(f"/sessions/{session_id}", status_code=303)


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
def review_page(request: Request, db: DBSession = Depends(get_db)):
    learner = db.exec(select(Learner)).first()
    card = cards.next_due(db, learner.id)
    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "card": card,
            "options": cards.rating_options(card) if card else [],
            "total": cards.due_count(db, learner.id),
        },
    )


@app.post("/review/{card_id}")
def review_answer(card_id: int, rating: int = Form(...), db: DBSession = Depends(get_db)):
    if rating not in (1, 2, 3, 4) or db.get(cards.Card, card_id) is None:
        raise HTTPException(400)
    cards.review(db, card_id, rating)
    return RedirectResponse("/review", status_code=303)


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
