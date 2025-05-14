import json
import re
from openai import OpenAI
import traceback
import mimetypes
import os
import aiohttp
import sys



async def download_apk(url, filename):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(filename, 'wb') as f:
                    while True:
                        chunk = await resp.content.read(1024 * 32)  # 32KB chunks
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        percent = (downloaded / total) * 100
                        sys.stdout.write(f"\r[download] Progress: {percent:.2f}%")
                        sys.stdout.flush()
                print(f"\n[download] APK downloaded to {filename}")
            else:
                raise Exception(f"Failed to download APK. HTTP status: {resp.status}")

def try_parse_json(text):
    
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    code_block_match = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", text, re.IGNORECASE)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1))
        except json.JSONDecodeError:
            pass


    return None


class LlmClient():

    def __init__(self):

        self.config = None
        self.client = None

        try:
            with open("llm_config.json") as f:
                self.config = json.loads(f.read())

            if self.config["base_url"] != "":
                self.client = OpenAI(
                    api_key=self.config["api_key"],
                    base_url=self.config["base_url"]
                )
            else:
                self.client = OpenAI(
                    api_key=self.config["api_key"]
                )
        
            

        except Exception as e:
            print(traceback.format_exc())


    def generate_title_for_conversation(self, task):
        
        messages = []
        title_task = f"""
            Here is the query:
            {task}

            Generate a concise title (no more than 5 words) that accurately reflects the main theme or topic of the query. Emojis can be used to enhance understanding but avoid quotation marks or special formatting. RESPOND ONLY WITH THE TITLE TEXT.
            If the query is conversational like "hello", "how are you?" etc.. just return "New Chat"

            Examples of titles:
            📉 Stock Market Trends
            🍪 Perfect chocolate chip recipe
            Evolution of Music Streaming
            Remote work productivity tips
            Artificial Intelligence in Healthcare
            🎮 Video Game Development Insights
        """
        messages.append({"role": "user", "content": title_task})

        try:
            completion = self.client.chat.completions.create(
                model=self.config["model_name"],
                messages=messages
            )
            result = completion.choices[0].message.content
            return result

        except Exception as e:
            print(traceback.format_exc())
            return None

    
    def generate(self, system_prompt, event_stream, base64_image=None):
        
        messages = []
        messages.append({"role": "system","content": system_prompt})

        if self.config["use_vision"] and base64_image is not None:
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": event_stream
                    },
                    {
                        "type": "input_image",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            })
        else:
            messages.append({"role": "user", "content": event_stream})
        
        try:
            completion = None

            if self.config["reasoning_effort"] in ["low", "medium", "high"]:
                completion = self.client.chat.completions.create(
                    model=self.config["model_name"],
                    messages=messages,
                    reasoning_effort=self.config["reasoning_effort"],
                    temperature=self.config["temperature"]
                )
            else:
                completion = self.client.chat.completions.create(
                    model=self.config["model_name"],
                    messages=messages,
                    temperature=self.config["temperature"]
                )


            result = completion.choices[0].message.content
            # print(result)
            return try_parse_json(result)

        except Exception as e:
            print(traceback.format_exc())
            return None


def get_tools():
    result = ""
    with open('tools.json', 'r') as f:
        data = json.load(f)
    for item in data:
        result += json.dumps(item) + '\n'

    return result


def construct_event_stream(state, show_clickables=False):

    event_stream = ""

    if show_clickables:
        event_stream += "<clickables>\n"

        keys_to_remove = {'coordinate_x', 'coordinate_y', 'left', 'right', 'top', 'bottom'}    
        filtered = [
            {k: v for k, v in elem.items() if k not in keys_to_remove}
            for elem in state["clickables"]
        ]

        to_jsonl = ""
        for elem in filtered:
            to_jsonl += json.dumps(elem) + "\n"

        event_stream += to_jsonl

        event_stream += "</clickables>\n\n"

    event_stream += "<event_stream>\n"

    for message in state["messages"]:
        if message["role"] == "user":
            event_stream += f"User Message: {message["content"]}\n"
        elif message["role"] == "tool":
            event_stream += f"Action: {message["content"]}\n"
        elif message["role"] == "function":
            event_stream += f"Observation: {message["content"]}\n"
        elif message["role"] == "shell":
            event_stream += f"Shell ID[{message["id"]}]: {message["result"]}\n"

    remaining_sessions = []

    for session in state["shell_sessions"]:
        session_id = session[0]
        session_task = session[1]

        if session_task.done():
            try:
                stdout, stderr, returncode = session_task.result()
                result = ""
                if returncode == 0:
                    if stdout:
                        result += f"Success: {stdout}"
                    elif stderr:
                        result += f"Error: Exit Code[{returncode}] {stderr}"
                else:
                    if stderr:
                        result += f"Error: Exit Code[{returncode}] {stderr}"
                    else:
                        result += f"Error: Exit Code[{returncode}]"

                state["messages"].append({
                    "role": "shell",
                    "id": session_id,
                    "result": result
                })

                event_stream += result
            except Exception as e:
                print(traceback.format_exc())
        else:
            remaining_sessions.append(session)


    state["shell_sessions"] = remaining_sessions
    event_stream += "</event_stream>"
    event_stream_length = len(event_stream)
    max_size = state.get("max_event_stream_size")

    if max_size is not None:
        if event_stream_length > max_size:
            diff = event_stream_length - max_size
            event_stream = event_stream[diff:]

    print(event_stream)
    return event_stream


def get_mime_type(path):
    file_name = os.path.basename(path)
    result = mimetypes.guess_type(path)[0]
    return file_name, result

# class ShellSession():

#     @classmethod
#     async def create(cls, serial):

#         self = cls()

#         command = ["adb", "-s", f"{serial}", "shell", "run-as", "com.termux", "files/usr/bin/bash",
#             "-lic", f"'export PATH=/data/data/com.termux/files/usr/bin:$PATH; export LD_PRELOAD=/data/data/com.termux/files/usr/lib/libtermux-exec.so; export HOME=/data/data/com.termux/files/home; export PS1='__PROMPT__'; bash -i'"]

#         DETACHED_PROCESS = 0x00000008
#         process = await asyncio.create_subprocess_exec(
#             *command,
#             stdin=asyncio.subprocess.PIPE,
#             stdout=asyncio.subprocess.PIPE,
#             stderr=asyncio.subprocess.STDOUT,
#             creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
#         )

#         self.input_queue = asyncio.Queue()
#         self.output_queue = asyncio.Queue()
#         self.id = process.pid
#         self.proc = process
#         self.stop_event = asyncio.Event()

#         return self



# class DroidResponse(BaseModel):
#     thought: str
#     action: str | None


# async def read_until_prompt(reader, return_line=False):
    
#     output_buffer = bytearray()
#     while True:
#         line = await reader.readline()

#         if not line:
#             raise EOFError("Subprocess closed during command output read")

#         if b"__PROMPT__" in line:
#             if return_line:
#                 return line
#             else:
#                 return output_buffer

#         output_buffer.extend(line)


# async def shell_loop(shell_session, device, websocket):
    
#     try:

#         while not shell_session.stop_event.is_set():
            
#             command = await shell_session.input_queue.get()
#             shell_session.input_queue.task_done()
#             shell_session.proc.stdin.write(command.encode() + b"\n")
#             await shell_session.proc.stdin.drain()

#             initial_command = ""
#             while True:

#                 line = await shell_session.proc.stdout.readline()
                
#                 if not line:
#                     raise EOFError("Subprocess closed during command output read")

                
#                 if b"__PROMPT__" in line:
#                     #pwd is swapped!??
#                     if command == "pwd":
#                         print("Next prompt detected: pwd")
#                     else:
#                         print(f"Next prompt detected: {line!r}")

                    
#                     initial_command = line.decode("utf-8").strip().split("__PROMPT__", 1)[1]
#                     break


#             shell_session.proc.stdin.write(b"\n")
#             await shell_session.proc.stdin.drain()

#             output_buffer = bytearray()
#             while True:
#                 line = await shell_session.proc.stdout.readline()
                
#                 if not line:
#                     raise EOFError("Subprocess closed before initial prompt")

#                 if b"__PROMPT__" in line:
#                      print("Output consumed.")
#                      break

#                 output_buffer.extend(line)


#             output = output_buffer.decode("utf-8").strip()

#             if output == "pwd":
#                 output = initial_command

#             print(output)

            
#     except Exception as e:
#         print(f"Shell loop error: {e!r}")
#     finally:
#         print(f"shell task ended for {shell_session.id}")
#         shell_session.proc.kill()
#         await shell_session.proc.wait()

