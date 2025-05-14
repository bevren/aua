# AUA(Android Use Agent)

First make sure you have adb installed on your computer.

Then, prepare an Android phone (not two) with Developer Options enabled, connect it to the computer, and make sure you can see the connected device by running `adb devices`.

Clone the repo `git clone https://github.com/bevren/aua.git`

Cd into repo.

Run `python -m pip install -r requirements.txt` to install requirements.

Open `llm_config.json`. Fill in values.

```json
{
	"base_url": "", // leave empty for openai.
	"api_key": "",
	"model_name": "",
	"reasoning_effort": "", //low, medium, high. for reasoning models.
	"temperature": 1,
	"use_vision": false,
	"max_event_stream_size": 10000, // in characters not in tokens. will truncate event stream
	"wait_before_generate": 3 //wait before generating response to avoid rate limits with free api. e.g gemini
}
```

Run `python main.py`



