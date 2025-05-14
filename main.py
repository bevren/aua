import xml.etree.ElementTree as ET
import re
import json
import gzip 
import base64
import websockets
import asyncio
import uiautomator2 as u2
from adbutils import adb
import http.server
import threading
import socketserver
import functools
import os

from openai import OpenAI
from utils import get_tools, construct_event_stream, try_parse_json, LlmClient, get_mime_type, download_apk
from prompt import get_system_prompt
from db import *
from io import BytesIO
from PIL import ImageDraw, ImageFont
import shlex
import traceback

APK_URL = "https://github.com/termux/termux-app/releases/download/v0.118.2/termux-app_v0.118.2+github-debug_universal.apk"
APK_FILENAME = "termux-app_v0.118.2+github-debug_universal.apk"
httpd = None

def connect_device(device_id):
    connected_device = None
    try:
        connected_device = u2.connect(device_id)
        print(f"[connect_device] Connected to {device_id}")
        return connected_device
    except Exception as e:
        print(f"[connect_device] Failed to connect to {device_id}:", e)
        return None

def list_devices():
    try:
        return [dev.serial for dev in adb.device_list()] 
    except Exception as e:
        print("failed to list devices")
        return []

def get_clickables(device):

    BOUNDS_REGEX = re.compile(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]')

    clickable_elements = []

    xml = device.dump_hierarchy(compressed=False, pretty=False, max_depth=50)


    try:
        root = ET.fromstring(xml) 
    except ET.ParseError as e:
        print(f"Error parsing XML after decompression: {e}")
        # print(xml_content[:500]) 
        return "[]" 

    index = 0
    for node in root.findall('.//node'): 
        if node.get('clickable') == 'true':
            bounds_str = node.get('bounds')
            if not bounds_str: continue 

            bounds_match = BOUNDS_REGEX.match(bounds_str)
            if bounds_match:
                left, top, right, bottom = map(int, bounds_match.groups())
                if right <= left or bottom <= top: continue

                element_info = {
                    'index': index,
                    # 'class': node.get('class', ''),
                    'resource_id': node.get('resource-id', ''),
                    'text': node.get('text', ''),
                    'content_desc': node.get('content-desc', ''),
                    # 'package': node.get('package', ''), 
                    'coordinate_x': int(round((left + right)/2)), 
                    'coordinate_y': int(round((top + bottom)/2)),
                    "left": left,
                    "right": right,
                    "top": top,
                    "bottom": bottom
                    
                }
                clickable_elements.append(element_info)
            else:
                print(f"Warning: Could not parse bounds string: {bounds_str}")

        index += 1

    print(f"Found {len(clickable_elements)} clickable elements.")

    return clickable_elements


async def capture_screenshot_base64_no_gzip(device, clickables):
    
    # clickables = await asyncio.to_thread(get_clickables, device)

    img = await asyncio.to_thread(device.screenshot)

    try:
        font = ImageFont.truetype("arial.ttf", size=24) 
    except IOError:
        font = ImageFont.load_default()

    draw = ImageDraw.Draw(img)
    for elem in clickables:
        left = elem['left']
        top = elem['top']
        right = elem['right']
        bottom = elem['bottom']
        x = elem['coordinate_x']
        y = elem['coordinate_y']
        index = elem["index"]
        draw.rectangle([left, top, right, bottom], outline="red", width=3)
        # draw.text((left, top - 4), str(elem.get('resource_id', '')), fill="red")
        draw.text((left + 4, top + 4), f"{index}", fill="red", font=font)

    # img.save("screenshot_with_boxes.jpg", format="JPEG", quality=70)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=70)
    jpeg_bytes = buf.getvalue()
    
    return base64.b64encode(jpeg_bytes).decode("utf-8")

async def capture_screenshot_base64(device):
    
    img = await asyncio.to_thread(device.screenshot)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=70)
    jpeg_bytes = buf.getvalue()
    
    compressed = gzip.compress(jpeg_bytes)
    return base64.b64encode(compressed).decode("utf-8")

async def send_screenshots_periodically(device, websocket):
    try:
        while True:
            b64_image = await capture_screenshot_base64(device)
            await websocket.send(json.dumps({"type":"screenshot", "data": b64_image}))
            await asyncio.sleep(1/60)
    except websockets.exceptions.ConnectionClosed:
        print("[Sender] WebSocket closed.")
    except Exception as e:
        print("[Sender] Error:", e)
        print(traceback.format_exc())


async def spawn_termux(cmd, serial, cwd=None):

    command_to_run = cmd
    if cwd:
        command_to_run = f'cd {cwd} && {cmd}'

    final_command = shlex.quote(f'export PATH=/data/data/com.termux/files/usr/bin:$PATH; '
        f'export LD_PRELOAD=/data/data/com.termux/files/usr/lib/libtermux-exec.so; '
        f'export HOME=/data/user/0/com.termux/files/home; '
        f'{command_to_run}')

    command = ["adb", "-s", f"{serial}", "shell", "run-as", "com.termux", "files/usr/bin/bash",
                "-c", final_command]

    DETACHED_PROCESS = 0x00000008
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=DETACHED_PROCESS,
    )

    return process


async def run_termux(cmd, serial, cwd=None):

    proc = await spawn_termux(cmd, serial, cwd)

    try:
        stdout, stderr = await proc.communicate()
        output = stdout.decode("utf-8", errors="ignore")
        error = stderr.decode("utf-8", errors="ignore")
        
        return output, error, proc.returncode
    except Exception as e:
        print(traceback.format_exc())

async def run_termux_timeout(cmd, serial, timeout=60):

    proc = await run_termux(cmd, serial)

    output = None
    error = None
    try:
        result = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        stdout, stderr = result
        output = stdout.decode("utf-8", errors="ignore")
        error = stderr.decode("utf-8", errors="ignore")
        return output, error, proc.returncode
    except asyncio.TimeoutError:
        error = f"TimeoutError: {cmd} timed out"
        proc.kill()
        await proc.wait()
        # if proc.returncode is None:
        #     parent = psutil.Process(proc.pid)
        #     for child in parent.children(recursive=True): 
        #         child.terminate()
        #     parent.terminate()
        #     print("Terminating Process '{0}' (timed out)".format(cmd))
    finally:
        return output, error, proc.returncode


async def install_apps(device, websocket):
    packages = await asyncio.to_thread(device.app_list, "-3")

    if "com.termux" not in packages:
        print("[shell] installing termux app")
        await websocket.send(json.dumps({"type": "info", "data": "Installing Termux app"}))
        await websocket.send(json.dumps({"type": "control", "success": True}))
        
        if not os.path.exists(APK_FILENAME):
            await download_apk(APK_URL, APK_FILENAME)
            print("[download] Completed.")

        await asyncio.sleep(3)
        await asyncio.to_thread(device.app_install,"termux-app_v0.118.2+github-debug_universal.apk")
        print("[shell] termux installed")
        await websocket.send(json.dumps({"type": "info", "data": "Termux installed"}))
        await websocket.send(json.dumps({"type": "control", "success": True}))
    else:
        print("[shell] com.termux package already installed on device")

    
    spinner = ['|', '/', '–', '\\']
    i = 0
    play_store = False
    print("initializing termux shell")
    await websocket.send(json.dumps({"type": "info", "data": "Initializing termux shell"}))
    while True:
        stdout, stderr, returncode = await run_termux("echo hello", device.serial)
        
        if returncode == 0:
            if i > 0:
                print(' ' * 50, end='\r', flush = True)
            print("termux shell launched")
            await websocket.send(json.dumps({"type": "info", "data": "Termux shell launched"}))
            break
        else:
            
            if "package not debuggable" in stderr:
                play_store = True
                print("You have play store version of termux. Uninstall it and run it again.")
                await websocket.send(json.dumps({"type": "info", "data": "You have play store version of termux. Uninstall it and run it again."}))
                break
            elif "files/usr/bin/bash" in stderr and i == 0:
                await asyncio.to_thread(device.app_start, "com.termux")

            if i == 0:
                await websocket.send(json.dumps({"type": "info", "data": "Waiting for termux shell to launch"}))
            
            print(f"Waiting termux shell to launch {spinner[i % len(spinner)]}", end='\r', flush=True)
            i += 1
    
    if play_store:
        return -1

    valid_python = True

    
    print("Checking for python...")
    await websocket.send(json.dumps({"type": "info", "data": "Checking for python..."}))
    stdout, stderr, returncode = await run_termux("python --version", device.serial)
    
    if returncode == 0:
        print(f"Python exists on device {stdout}")
        await websocket.send(json.dumps({"type": "info", "data": f"Python exists on device {stdout}"}))
        
    else:
        print("Updating packages using pkg upgrade")
        await websocket.send(json.dumps({"type": "info", "data": "Updating packages using pkg upgrade..."}))
        _, _, _ = await run_termux("pkg upgrade", device.serial)
    
        print("Installing python...")
        await websocket.send(json.dumps({"type": "info", "data": "Python is not detected."}))
        await websocket.send(json.dumps({"type": "info", "data": "Installing python this may take some time..."}))

        _, stderr, returncode = await run_termux("pkg install -y python", device.serial)
        
        if returncode == 0:
            print("Python installed succesfully")
            await websocket.send(json.dumps({"type": "info", "data": "Python installed succesfully"}))
        else:
            print(stderr)
            valid_python = False
            print("Failed to install python")
            await websocket.send(json.dumps({"type": "info", "data": "Failed to install python"}))

        


    if valid_python:
        print("DEVICE_READY")
        
        _, _, returncode = await run_termux("mkdir workspace", device.serial)
        
        if returncode == 0:
            print("created a workspace folder")
        
        await websocket.send(json.dumps({"type": "info", "data": "DEVICE_READY"}))
        await websocket.send(json.dumps({"type": "device_ready"}))

def generate_llm_no_image(client, system_prompt, event_stream):
    result = None
    try:
        completion = client.chat.completions.create(
            model="gemini-2.0-flash",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": event_stream},
            ]
        )

        result = completion.choices[0].message.content
        print(result)
    except Exception as e:
        print(traceback.format_exc())


    return try_parse_json(result)


def generate_llm_with_image(client, system_prompt, event_stream, base64_image):
    
    result = None
    try:
        completion = client.chat.completions.create(
            model="gemini-2.0-flash",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {
                        "type": "text",
                        "text": event_stream
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        } 
                    }
                ]},
            ]
        )

        result = completion.choices[0].message.content
        print(result)
    except Exception as e:
        print(traceback.format_exc())


    return try_parse_json(result)


async def file_write(serial, file, content, append=None, leading_newline=None, trailing_newline=None):
    
    command = "printf %s "

    if leading_newline:
        content = "\n" + content
    if trailing_newline:
        content = content + "\n"

    safe_content = content.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`")

    command += f'"{safe_content}"'

    if append:
        command += f'>> {file}'
    else:
        command += f'> {file}'
    
    stdout, stderr, returncode = await run_termux(command, serial)
    print(stderr)
    result = f"{content}" if returncode == 0 else f"Error: {stderr}"

    return result


async def file_find_in_content(serial, file = None, regex=None):
    if file is None or regex is None:
        return "Error: Missing required arguments: file, regex"


    command = f"grep -E {file} {regex}"

    stdout, stderr, returncode = await run_termux(command, serial)
    print(stderr)

    result = f"Success: {stdout}" if returncode == 0 else f"Error: {stderr}"

    return result


async def file_find_by_name(serial, path=None, glob=None):
    if not path or not glob:
        return "Error: Missing required arguments: path, glob"

    command = f"find {path} -type f -name {glob}"

    stdout, stderr, returncode = await run_termux(command, serial)
    print(stderr)

    result = f"Success: {stdout}" if returncode == 0 else f"Error: {stderr}"

    return result

def sed_escape(text):
    result = text.replace("\n", "\\n")
    # .replace('[', '\\[').replace('*', '\\*').replace('$', '\\$').replace('.', '\\.').replace('^', '\\^')
    return result


async def file_str_replace(serial, file=None, old_str=None, new_str=None):
    if not file or old_str is None or new_str is None:
        return "Error: Missing required arguments: file, old_str, new_str"

    if file.startswith("/"):
        file = file[1:]

    old_str = sed_escape(old_str)
    new_str = sed_escape(new_str)

    print(old_str, new_str)

    command = f"sed -i 's/{old_str}/{new_str}/g' {file}"

    stdout, stderr, returncode = await run_termux(command, serial)
    print(stderr)

    result = f"Success: {stdout}" if returncode == 0 else f"Error: {stderr}"

    return result


async def create_project_folder(serial, project_name):
    result = ""
    command = f"mkdir workspace/{project_name}"
    _, stderr, returncode = await run_termux(command, serial)


    result = f"Success: Folder created workspace/{project_name}" if returncode == 0 else f"Error: Folder exists workspace/{project_name} proceed to next step."

    return result, f"workspace/{project_name}"

async def file_read(serial, file, start_line=None, end_line=None):
    if not file:
        return "Error: Missing required arguments: file"


    if file.startswith("/"):
        file = file[1:]

    if start_line is not None and end_line is not None:
        command = f"sed -n '{start_line},{end_line}p' {file}"
    elif start_line is not None:
        command = f"tail -n +{start_line} {file}"
    else:
        command = f"cat {file}"

    stdout, stderr, returncode = await run_termux(command, serial)

    result = f"{stdout}" if returncode == 0 else f"Error: {stderr}"

    return result


async def run_process():
    try:
        stdout, stderr = await process.communicate()    
        return stdout.decode("utf-8", errors="ignore"), stderr.decode("utf-8", errors="ignore"), process.returncode
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        print(traceback.format_exc())
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()

async def shell_exec(serial, id, exec_dir, command, long_running=None):
    if not exec_dir or not command or not id:
        return "Error: Missing required arguments: id, exec_dir, command"
    
    if exec_dir.startswith("/"):
        exec_dir = exec_dir[1:]

    if long_running:
        task = asyncio.create_task(run_termux(command, serial, exec_dir))
        return task  
    else:
        return await run_termux(command, serial, exec_dir)


async def shell_kill_process(state, id):

    if not id:
        return "Error: Missing required arguments: id"


    for session in state["shell_sessions"]:
        session_id = session[0]
        session_task = session[1]
        if session_id == id:
            if session_task:
                session_task.cancel()
                try: await session_task
                except asyncio.CancelledError: pass
                return f"Success: Terminated process with {session_id}."


    return f"Error: Failed to terminate process {id}"

async def message_notify_user(state, websocket, text):
    if not text:
        return "Error: Missing required arguments: text"

    await websocket.send(json.dumps({"type": "notify", "data": text}))
    return f"Success: notified user, proceed to next step."

async def message_ask_user(state, websocket, text, suggest_user_takeover=None):
    if not text:
        return "Error: Missing required arguments: text"

    await websocket.send(json.dumps({"type": "ask_user", "data": text}))
    return f"Success: waiting for user response."


async def click(state, device, index=None, coordinate_x=None, coordinate_y=None):
    clickable_found=None
    if index is not None:
        
        if type(index) is not int:
            return "Error: Invalid value for argument index, must be integer."

        for i, clickable in enumerate(state["clickables"]):
            if clickable["index"] == index:
                clickable_found = state["clickables"][i]
                
        if clickable_found:
            x = clickable_found["coordinate_x"]
            y = clickable_found["coordinate_y"]

            if x and y:
                await asyncio.to_thread(device.click, x, y)
                return f"Success: clicked on {index}"
            # d(text='Clock', className='android.widget.TextView')
        else:
            return f"Error: There is no UI element with index={index}"
    else:
        if coordinate_x is not None and coordinate_y is not None:
            await asyncio.to_thread(device.click, coordinate_x, coordinate_y)
            return f"Success:  click[{coordinate_x}, {coordinate_y}]"
        else:
            return "Error: Missing argument index, coordinate_x, coordinate_y"


async def set_text(state, device, index=None, text_input=None, press_enter=None, clear=None):

    if index is None  or text_input is None or press_enter is None:
        return "Error: Missing required arguments: index, text_input, press_enter"

    clickable_found=None
    for i, clickable in enumerate(state["clickables"]):
        if clickable["index"] == index:
            clickable_found = state["clickables"][i]
                   
    if clickable_found:

        # if clear is not None:
        #     if clear == True:
        #         device(resourceId=clickable["resource_id"], text=clickable["text"]).clear_text()

        # device(resourceId=clickable["resource_id"], text=clickable["text"]).set_text(text_input)
        # result = f"Success"

        # if press_enter:
        #     device.send_action()

        x = clickable_found["coordinate_x"]
        y = clickable_found["coordinate_y"]

        if x and y:
            await asyncio.to_thread(device.click, x, y)
            
            if clear is not None:
                await asyncio.to_thread(device.send_keys, text_input, clear=clear)
            else:
                await asyncio.to_thread(device.send_keys, text_input)

            if press_enter == True:
                await asyncio.sleep(1)
                device.send_action()

            return f"Success: set_text[{text_input}]"
            

    else:
        return f"Error: There is no UI element with index {index}"

async def handle_function_call(action, state, websocket):

    if not type(action) is dict:
        return "Error: Invalid format for action. Must be a JSON instead got string"

    function_name = action.get("action", None)
    args = action.get("parameters", None)
    device = state["connected_device"]
    serial = device.serial
    result = ""

    if function_name is None:
        return f"Error: Invalid response missing action"

    if args is None:
        return f"Error: Missing argument 'parameters'"

    if function_name == "create_project_folder":
        result, full_path= await create_project_folder(serial=serial, **args)
        if db_update_conversation_directory(state["db"], state["conversation_id"], full_path):
            print(f"[db] succesfully set working directory {full_path} for {state["conversation_id"]}")
        else:
            print(f"[db] failed to set working directory {full_path} for ${state["conversation_id"]}")

    elif function_name == "file_write":
        try:
            result = await file_write(serial=serial, **args)
        except Exception as e:
            result = str(e)
            print(traceback.format_exc())

    elif function_name == "file_read":
        result = await file_read(serial=serial, **args)
    elif function_name == "shell_exec":

        if args.get("long_running") is not None and args.get("long_running") == True:
            task = await shell_exec(serial=serial, **args)
            if task:
                state["shell_sessions"].append((args["id"], task))
                result = f"Success: created long running task for {args["id"]}"
            else:
                result = f"Error: Failed to create long running task for {args["id"]} command {args["command"]}"

        else:
            stdout, stderr, returncode = await shell_exec(serial=serial, **args)
            result = f"Success: {stdout}" if returncode == 0 else f"Error: {stderr}"
    elif function_name == "shell_kill_process":
        result = await shell_kill_process(state=state, **args)
    elif function_name == "open_browser":
        output, returncode = await asyncio.to_thread(device.shell, "am start -a android.intent.action.VIEW -d http://www.google.com --es com.android.browser.application_id com.package.name")
        result = "Success" if returncode == 0 else "Error: Failed to open browswer"

    elif function_name == "get_clickables":
        clickables = await asyncio.to_thread(get_clickables, device)
        state["clickables"] = clickables
        # print(state["clickables"])
        keys_to_remove = {'left', 'right', 'top', 'bottom'}
        filtered = [
            {k: v for k, v in elem.items() if k not in keys_to_remove}
            for elem in clickables
        ]

        to_jsonl = ""
        for elem in filtered:
            to_jsonl += json.dumps(elem) + "\n"


        result = to_jsonl

    elif function_name == "click":
        try:
            result = await click(state, device, **args)
        except Exception as e:
            result = str(e)
            print(traceback.format_exc())

        # .click(payload["data"][0], payload["data"][1])
    elif function_name == "set_text":
        try:
            result = await set_text(state, device, **args)
        except Exception as e:
            result = str(e)
            print(traceback.format_exc())
        
    elif function_name == "go_back":
        device.press("back")
        result = "Success: Pressed back button"
    elif function_name == "go_home":
        device.press("home")
        result = "Success: Pressed home button"
    elif function_name == "run_application":
        name = args.get("name", None)
        if name is not None:
            try:
                await asyncio.to_thread(device.app_start, args["name"], use_monkey=True)
                result = f"Success: Started app {args["name"]}"
            except Exception as e:
                result = f"Error: {str(e)}"
        else:
            result = "Error: Missing required argument 'name'"
    elif function_name == "list_applications":
        try:
            packages = await asyncio.to_thread(device.app_list, "-3")
            result = "\n".join(packages)
        except Exception as e:
            result = f"Error: {str(e)}"
            print(traceback.format_exc())

    elif function_name == "swipe":

        clickable_found=None
        direction = None
        distance = None

        if args.get("index") is not None:
            for i, clickable in enumerate(state["clickables"]):
                if clickable["index"] == args["index"]:
                    print(f"clickable found index {i}")
                    clickable_found = state["clickables"][i]

        if args["direction"] is not None:
            direction = args["direction"]

        if args["distance"] is not None:
            distance = args["distance"]

        if direction is None or distance is None:
            result = "Error: Missing required arguments direction, distance"
        else:
            if clickable_found:
                device(text=clickable_found["text"], className=clickable_found["class"]).swipe(direction)
            else:
                distance_scale = 1.0 if distance == "long" else 0.5 if distance == "medium" else 0.25 
                
                if direction == "down":
                    direction = "up"
                elif direction == "up":
                    direction = "down" 

                device.swipe_ext(direction, scale=distance_scale)
                result = f"Success: swipe[{direction}]"

    elif function_name == "wait_for_seconds":
        secs = args.get("seconds", None)
        if secs is None:
            result = "Error: Missing required argument seconds."
        elif secs > 60:
            result = f"Error: No more than 60 seconds but got {secs} seconds."
        else:
            await asyncio.sleep(secs)
            result = f"Success: waited for {secs} seconds."
    elif function_name == "message_notify_user":
        result = await message_notify_user(state=state, websocket=websocket, **args)
    elif function_name == "message_ask_user":
        result = await message_ask_user(state=state, websocket=websocket, **args)
    elif function_name == "file_str_replace":
        result = await file_str_replace(serial, **args)
    elif function_name == "file_find_in_content":
        result = await file_find_in_content(serial, **args)
    elif function_name == "file_find_by_name":
        result = await file_find_by_name(serial, **args)
    else:
        result = "Not implemented"

    # print(action)
    # print(function_name)
    print("RESULT: ", result)
    # print(**args)

    return result


async def agent_loop(llm, state, websocket):
    print("[agent_loop] started")
    
    try:

        device = state["connected_device"]    
        tools = get_tools()
        system_prompt = get_system_prompt(tools)
        db = state["db"]
        
        if state["conversation_id"] is None and len(state["messages"]) == 1:
            print("[agent_loop] Initial query received. Generating title...")
            task = state["messages"][0]["content"]
            title = await asyncio.to_thread(llm.generate_title_for_conversation, task)
            
            if title is None:
                title = "New Chat"
                print(f"[agent_loop] Failed to generate title setting default title: {title}")
            else:
                print(f"[agent_loop] Title generated: {title}")    
            
            print("[agent_loop] Inserting new conversation to database")
            result = db_new_conversation(db, device.serial, state["messages"], title)
            
            if result is not None:
                state["conversation_id"] = result["conversationId"]
                print(f"[agent_loop] New conversation added to database: {result["conversationId"]}")
                await websocket.send(json.dumps({
                    "type": "new_conversation",
                    "conversationId": state["conversation_id"],
                    "title": title 
                }))
            else:
                print(f"[agent_loop] Failed to create new conversation")
                return

        while True:
            
            state["clickables"] = await asyncio.to_thread(get_clickables, device)
            local_event_stream = construct_event_stream(state, True)
            
            base64_image = None
            if llm.config["use_vision"]:
                base64_image = await capture_screenshot_base64_no_gzip(device, state["clickables"])

            # result = await asyncio.to_thread(generate_llm_with_image, client, system_prompt, local_event_stream, base64_image)
            result = await asyncio.to_thread(llm.generate, system_prompt, local_event_stream, base64_image)
            
            # print(local_event_stream)
            print(result)

            if result:
                
                action = result.get('action', None)

                if action is None or not type(action) is str:
                    continue
                
                to_send_result = json.dumps(result)

                state["messages"].append({
                    "role": "tool",
                    "content": to_send_result
                })

                await websocket.send(json.dumps({"type": "action", "data": to_send_result}))

                tool_result = await handle_function_call(result, state, websocket)    

                state["messages"].append({
                    "role": "function",
                    "content": tool_result
                })
                
                await websocket.send(json.dumps({
                    "type": "tool_response",
                    "tool": to_send_result, 
                    "result": tool_result
                }))

                if action == "message_ask_user":
                    break

                if action == "idle":
                    break

            secs = state.get("wait_before_generate")

            if secs is not None:
                await asyncio.sleep(secs)
            else:
                await asyncio.sleep(3)
            
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(traceback.format_exc())
    finally:
        print("[agent_loop] stopped")
        await websocket.send(json.dumps({"type": "agent_state", "data": "stop"}))
        if state.get("conversation_id") is not None:
            if db_update_conversation_messages(db, state["conversation_id"], state["messages"]):
                print(f"[agent_loop] Successfuly updated {state["conversation_id"]} messages")
            else:
                print(f"[agent_loop] Failed to update {state["conversation_id"]} messages")


def clear_state(state):
    state["messages"] = []
    state["clickables"] = []
    state["conversation_id"] = None
    state["shell_sessions"] = []
    
clients = set()
async def handle_client(websocket):
    
    state = {
        "messages": [],
        "serial": "",
        "connected_device": None,
        "shell_sessions": [],
        "clickables": [],
        "db": None,
        "conversation_id": None,
        "current_directory": "",
        "max_event_stream_size": "",
        "wait_before_generate": 0
    }

    llm = LlmClient()

    if llm.client is None:
        print("Failed to create LlmClient check llm_config.json")
        await websocket.close()
        return

    state["max_event_stream_size"] = llm.config["max_event_stream_size"] if llm.config.get("max_event_stream_size") is not None else 10000
    state["wait_before_generate"] = llm.config["wait_before_generate"] if llm.config.get("wait_before_generate") is not None else 3

    db = db_new_connection()

    if db is None:
        print("Failed to connect database")
        await websocket.close()
        return

    state["db"] = db
    agent_task = None
    screenshot_task = None
    
    print("[Server] Client connected.")
    clients.add(websocket)
    
    devices = await asyncio.to_thread(list_devices)
    await websocket.send(json.dumps({"type":"list_devices", "data": devices}))

    try:
        while True:
            message = await websocket.recv()
                
            try:
                payload = json.loads(message)
                if payload["type"] == "swipe":
                    state["connected_device"].swipe_points([(d[0], d[1]) for d in payload["data"]], 0.1)
                elif payload["type"] == "tap":
                    state["connected_device"].click(payload["data"][0], payload["data"][1])
                elif payload["type"] == "input":
                    if type(payload["data"]) is int:
                        if payload["data"] == 13:
                            state["connected_device"].press("enter")
                        elif payload["data"] == 8:
                            state["connected_device"].press("del")
                    else: 
                        state["connected_device"].send_keys(payload["data"], clear=False)
                elif payload["type"] == "scroll_up":
                    pass
                elif payload["type"] == "scroll_down":
                    pass
                elif payload["type"] == "connect_to_device":
                    
                    if state["connected_device"]:

                        if agent_task:
                            agent_task.cancel()
                            try: await agent_task
                            except asyncio.CancelledError: pass
                        
                        if screenshot_task:
                            screenshot_task.cancel()
                            try: await screenshot_task
                            except asyncio.CancelledError: pass


                    state["connected_device"] = connect_device(payload["data"])
                    
                    if state["connected_device"]:
                        await websocket.send(json.dumps({"type":"device_connected", "data": state["connected_device"].info}))
                        # conversations = await asyncio.to_thread(get_conversations, payload["data"])
                        # await websocket.send(json.dumps({"type":"list_conversations", "data": conversations}))
                        screenshot_task = asyncio.create_task(send_screenshots_periodically(state["connected_device"], websocket))
                        install_task = asyncio.create_task(install_apps(state["connected_device"], websocket))
                        conversations = db_get_conversation_list(state["db"], state["connected_device"].serial)
                        await websocket.send(json.dumps({"type": "conversation_list", "data": conversations}))
                    else:
                        await websocket.send(json.dumps({"type":"error", "data": "failed to connect device"}))
                elif payload["type"] == "message":

                    if agent_task:
                        agent_task.cancel()
                        try: await agent_task
                        except asyncio.CancelledError: pass
                        await websocket.send(json.dumps({"type": "agent_state", "data": "stop"}))

                    state["messages"].append({
                        "role": "user",
                        "content": payload["data"]
                    })
                    agent_task = asyncio.create_task(agent_loop(llm, state, websocket))
                    await websocket.send(json.dumps({"type": "agent_state", "data": "start"}))

                elif payload["type"] == "list_devices":
                    devices = list_devices()
                    await websocket.send(json.dumps({"type":"list_devices", "data": devices}))
                
                elif payload["type"] == "control":

                    if payload["data"] == "take":
                        if agent_task:
                            agent_task.cancel()
                            try: await agent_task
                            except asyncio.CancelledError: pass
                            await websocket.send(json.dumps({"type": "agent_state", "data": "stop"}))
                        await websocket.send(json.dumps({"type": "control", "success": True}))
                    elif payload["data"] == "release":
                        await websocket.send(json.dumps({"type": "control", "success": True}))
                    else:
                        print("invalid data for control command")

                elif payload["type"] == "new_chat":
                    if agent_task:
                        agent_task.cancel()
                        try: await agent_task
                        except asyncio.CancelledError: pass
                        await websocket.send(json.dumps({"type": "agent_state", "data": "stop"}))

                    state["messages"] = []
                    state["clickables"] = []
                    state["conversation_id"] = None
                    state["shell_sessions"] = []

                elif payload["type"] == "agent_state":
                    agent_state = payload["data"]

                    if agent_state == "stop":
                        if agent_task:
                            agent_task.cancel()
                            try: await agent_task
                            except asyncio.CancelledError: pass
                            await websocket.send(json.dumps({"type": "agent_state", "data": "stop"}))
                    elif agent_state == "start":
                        if agent_task:
                            agent_task.cancel()
                            try: await agent_task
                            except asyncio.CancelledError: pass

                        agent_task = asyncio.create_task(agent_loop(llm, state, websocket))             
                        await websocket.send(json.dumps({"type": "agent_state", "data": "start"}))

                elif payload["type"] == "get_conversation":

                    if agent_task:
                        agent_task.cancel()
                        try: await agent_task
                        except asyncio.CancelledError: pass


                    conversation_id = payload["data"]

                    result = db_get_conversation_by_id(state["db"], conversation_id)

                    if result is not None:
                        state["messages"] = result["messages"];
                        state["conversation_id"] = conversation_id
                        state["clickables"] = []
                        state["shell_sessions"] = []
                        
                        await websocket.send(json.dumps({"type": "get_conversation", "data": result}))
                    else:
                        await websocket.send(json.dumps({"type": "error", "data": "get_conversation"}))

                elif payload["type"] == "delete_conversation":
                    
                    conversation_id = payload["id"]

                    result = db_delete_conversation_by_id(state["db"], conversation_id)

                    if result is not None:
                        print(f"[db] succesfully delete conversation {conversation_id}")
                        if state["conversation_id"] == conversation_id:
                            if agent_task:
                                agent_task.cancel()
                                try: await agent_task
                                except asyncio.CancelledError: pass
                                await websocket.send(json.dumps({"type": "agent_state", "data": "stop"}))


                            state["messages"] = []
                            state["clickables"] = []
                            state["conversation_id"] = None
                            state["shell_sessions"] = []

                        if result != "none":
                            command = f"rm -rf {result}"
                            stdout, stderr, returncode = await run_termux(command, state["connected_device"].serial)

                            if returncode == 0:
                                print(f"[shell] succesfully removed directory {result}")
                            else:
                                print(f"[shell] Error: {stderr}")

                        await websocket.send(json.dumps({"type": "conversation_deleted", "data": conversation_id}))
                    else:
                        message = "Failed to remove conversation"
                        print(message)
                        await websocket.send(json.dumps({"type": "error", "data": message}))

                elif payload["type"] == "download_attachment":
                    file_path = payload["data"]

                    file_name, mime_type = get_mime_type(file_path)

                    command = f"base64 < {file_path}"
                    stdout, stderr, returncode = await run_termux(command, state["connected_device"].serial)


                    if returncode == 0:
                        await websocket.send(json.dumps({"type": "download_attachment", "base64": stdout, "mimeType": mime_type, "fileName": file_name}))
                    else:
                        await websocket.send(json.dumps({"type": "error", "data": "Failed to download attachment."}))


            except Exception as e:
                print("Invalid format for received message. Must be json object", e)
                pass
            print("[Server] Received from client:", message)
    

    except websockets.exceptions.ConnectionClosed:
        print("[Server] Client disconnected.")
        clients.discard(websocket)

        if agent_task:
            agent_task.cancel()
            try: await agent_task
            except asyncio.CancelledError: pass

        if screenshot_task:
            screenshot_task.cancel()
            try: await screenshot_task
            except asyncio.CancelledError: pass

    finally:
        db.close()

def start_http_server():
    global httpd
    PORT = 8000
    Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory="frontend")
    httpd = socketserver.ThreadingTCPServer(("", PORT), Handler)
    print(f"[HTTP] Serving frontend at http://localhost:{PORT}")
    httpd.serve_forever()



async def main():
    
    db_init()

    stop_event = asyncio.Event()

    httpd_thread = threading.Thread(target=start_http_server, daemon=True)
    httpd_thread.start()
    
    server = await websockets.serve(handle_client, "0.0.0.0", 8765)
    print("[WS] WebSocket server running on ws://localhost:8765")

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        print("\n[System] Shutting down on Ctrl+C...")
    finally:
        server.close()
        await server.wait_closed()
        
        if httpd:
            httpd.shutdown()
            print("[HTTP] Server shut down.")

        httpd_thread.join()    
        print("[System] Shutdown complete.")

    


if __name__ == "__main__":
    asyncio.run(main())