-- Language Trainer launcher: starts the local server, opens the page in the browser,
-- and stops the server when the app is quit. PROJECT_DIR and EXTRA_PATH are filled in by scripts/make_mac_app.sh.
property port : "8000"
property projectDir : "__PROJECT_DIR__"
property extraPath : "__EXTRA_PATH__"
property serverPid : ""

on isUp()
	try
		do shell script "/usr/bin/curl -s -o /dev/null --max-time 1 http://127.0.0.1:" & port & "/"
		return true
	on error
		return false
	end try
end isUp

on startServer()
	-- If something already answers (for example a server started from a terminal), use it and do not own it.
	if isUp() then return
	set cmd to "export PATH=" & quoted form of extraPath & ":$PATH; cd " & quoted form of projectDir & " && mkdir -p data && nohup .venv/bin/langtrainer >> data/server.log 2>&1 & echo $!"
	set serverPid to do shell script cmd
	repeat 80 times
		if isUp() then exit repeat
		delay 0.5
	end repeat
	if not isUp() then
		display alert "Language Trainer did not start" message "See " & projectDir & "/data/server.log" as critical
	end if
end startServer

on openPage()
	open location "http://127.0.0.1:" & port & "/"
end openPage

on run
	startServer()
	openPage()
end run

-- Clicking the Dock icon again
on reopen
	startServer()
	openPage()
end reopen

on quit
	if serverPid is not "" then
		try
			do shell script "kill " & serverPid
		end try
	end if
	continue quit
end quit
