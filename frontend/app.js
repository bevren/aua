
Element.prototype.hide = function() {
    this.classList.add("hidden")
}
Element.prototype.show = function() {
    this.classList.remove("hidden")
}



let ws = null;
let retryInterval = 2000; 
let retryTimer = null;
let resizeTimeout = null;

const screenshot = document.getElementById('wrapper');
const img = document.getElementById('screenshot');
const canvas = document.getElementById('swipe-canvas');
const ctx = canvas.getContext('2d');
const ss_status = document.getElementById('ss-status');

let startPos = null;
let currentPos = null;

let conversations = [];
let current_steps = [];
//let current_step_index = 0;
let currentConversation = "";
let selectedConversation = "";

let devices = [];
let current_device = null;
let current_device_selected = null;

const deviceSelect = document.getElementById('device-select');
const connectDeviceBtn = document.getElementById('connect-device-btn');
const refreshDeviceBtn = document.getElementById('refresh-device-btn');

const messages = document.getElementById('messages');
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const agentStateBtn = document.getElementById('agent-state-btn');
const newChatBtn = document.getElementById('new-chat-btn');
const listConversationsBtn = document.getElementById('list-conversations-btn');
const conversationControls = document.getElementById('conversation-controls');
const conversationListBody = document.querySelector('.conversation-list-body');

const modal = document.getElementById('delete-modal');
const modalOutput = document.getElementById('modal-output');
const modalDeleteBtn = document.getElementById('model-delete-button')
const modalCancelBtn = document.getElementById('model-cancel-button')
const showMainBtn = document.getElementById("showMainBtn");

const deviceControlButtons = document.querySelector('.device-button-group');
const takeControlButton = document.getElementById('take-control');
const sidebar = document.getElementById("conversation-list-container");

function disableHoverOnClick(element) {

	element.addEventListener('click', function() {
		element.classList.add('no-hover');
	});

	element.addEventListener('mouseleave', function() {
		element.classList.remove('no-hover');
	});
}
const elements = document.querySelectorAll('.icon-button');
elements.forEach(disableHoverOnClick);

function openSidebar(){
	sidebar.style.right = "0px"
	sidebar.setAttribute("data-open", "true")
}

function closeSidebar(){
	sidebar.style.right = "-230px"
	sidebar.setAttribute("data-open", "false")
}

listConversationsBtn.addEventListener('click', () => {
	const sidebarOpen = sidebar.getAttribute("data-open");
	
	if(sidebarOpen === "false"){
		openSidebar();
	}
	else if(sidebarOpen === "true") {
		closeSidebar();
	}
})

function updateCanvasSize() {
    canvas.width = screenshot.clientWidth;
    canvas.height = screenshot.clientHeight;
    canvas.style.width = screenshot.clientWidth + 'px';
    canvas.style.height = screenshot.clientHeight + 'px';
}
window.addEventListener('resize', updateCanvasSize);


let isFocused = false;

screenshot.addEventListener('focus', () => {
    isFocused = true;
    console.log("focused")
});

screenshot.addEventListener('blur', () => {
    isFocused = false;
    console.log("unfocused")
});


screenshot.addEventListener('mousedown', (e) => {
	const hasControl = takeControlButton.getAttribute("has-control") === "true";

	if(!hasControl) return;

    const rect = screenshot.getBoundingClientRect();
    startPos = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top
    };
});

screenshot.addEventListener('mousemove', (e) => {
    if (!startPos) return;

    const rect = screenshot.getBoundingClientRect();
    currentPos = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top
    };


    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    ctx.beginPath();
    ctx.arc(startPos.x, startPos.y, 10, 0, Math.PI * 2); 
    ctx.strokeStyle = 'lime';
    ctx.lineWidth = 3;
    ctx.stroke();


    ctx.beginPath();
    ctx.moveTo(startPos.x, startPos.y);
    ctx.lineTo(currentPos.x, currentPos.y);
    ctx.strokeStyle = 'red';
    ctx.lineWidth = 2;
    ctx.stroke();
});

screenshot.addEventListener('mouseup', (e) => {
    if (!startPos) return;

    const rect = screenshot.getBoundingClientRect();
    const endPos = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top
    };

    const startNorm = {
        x: startPos.x / rect.width,
        y: startPos.y / rect.height
    };
    const endNorm = {
        x: endPos.x / rect.width,
        y: endPos.y / rect.height
    };

    const deviceWidth = current_device.displayWidth;
    const deviceHeight = current_device.displayHeight;

    const swipeStart = [
        Math.round(startNorm.x * deviceWidth),
        Math.round(startNorm.y * deviceHeight)
    ];
    const swipeEnd = [
        Math.round(endNorm.x * deviceWidth),
        Math.round(endNorm.y * deviceHeight)
    ];

    let data = []
    data.push(swipeStart)
    data.push(swipeEnd)

     if (swipeStart[0] === swipeEnd[0] && swipeStart[1] === swipeEnd[1]) {
         if(ws && ws.readyState === WebSocket.OPEN) {
         	ws.send(JSON.stringify({
	          type: 'tap',
	          data: [swipeEnd[0], swipeEnd[1]]
	        }));
         }
    } else {
        console.log(`Swipe from ${swipeStart} to ${swipeEnd}`);
        if(ws && ws.readyState === WebSocket.OPEN) {
	    	ws.send(JSON.stringify({
	          type: 'swipe',
	          data: data
	        }));
	    }
    }

    
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    startPos = null;
    currentPos = null;
});


function connectWebSocket() {
	const status = document.getElementById('status');
	const indicator = document.getElementById('status-indicator');
  	ws = new WebSocket('ws://localhost:8765'); // Change to your WebSocket URL

	ws.onopen = function() {
		status.textContent = 'Connected';
		indicator.style.backgroundColor="#00ff00";
		console.log('WebSocket connected');
		ss_status.innerText = "Waiting for device connection...";
		clearInterval(retryTimer); 
		retryTimer = null;
	};

  ws.onmessage = function(event) {
    try {
      const message = JSON.parse(event.data);

      if (message.type === 'screenshot') {
        const base64 = message.data;

        const binaryString = atob(base64);
        const len = binaryString.length;
        const bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) {
          bytes[i] = binaryString.charCodeAt(i);
        }

        const decompressed = window.pako.ungzip(bytes);
        const blob = new Blob([decompressed], { type: 'image/png' });
        const url = URL.createObjectURL(blob);

        document.getElementById('screenshot').src = url;

        if(!resizeTimeout) {
        	resizeTimeout = setTimeout(updateCanvasSize, 1000);
        }
      }
      else if(message.type === 'list_devices') {
      	devices = message.data;
      	onDeviceListReceived(devices);
      }
      else if(message.type === 'device_connected') {
      	current_device = message.data;
      	onDeviceConnected(current_device);
      	setTimeout(updateCanvasSize, 1000);
      	
      }
      else if(message.type === 'error') {
      	console.error(message.data);
      }
      else if(message.type === 'control') {
      	endTakeControl(message.success);
      }
      else if(message.type === 'info') {
      	console.log(message.data)
      	addMessage(message.data, 'info');
      }
      else if(message.type === 'notify'){
      	//const msg = marked.parse(message.data)
      	//addMessage(msg, 'assistant');
      }
      else if(message.type === 'action') {

      	const data = JSON.parse(message.data)

      	const action = data.action;
      	const args = data.parameters;

      	current_steps.push({
      		"tool": data,
      		"result": ""
      	})
      	const current_step_index = current_steps.length - 1;
      	console.log(action, args, current_step_index);
      	
      	const toolHtml = getToolHtml(data, current_step_index, true);
      	addMessage(toolHtml, 'assistant');
      	
      }
      else if (message.type === 'tool_response') {
      	const tool =  JSON.parse(message.tool);
      	
      	const action = tool.action;
      	const args = tool.parameters;

      	const toolResult = message.result;
      	current_steps[current_steps.length - 1].result = toolResult;
      	
      	const crossEmoji = "&#10060;"
      	const checkmarkEmoji="&#10004;&#65039;"

      	const lastElement = messages.lastChild;

      	const spinner = lastElement.querySelector('.spinner-small');
      	if(spinner){
      		spinner.remove()
      	}

      	fixMark(toolResult, lastElement);

      	onToolButtonPressed(action, args, toolResult);

      }
      else if(message.type === 'device_ready'){
      	messages.innerHTML = "";
      	chatInput.disabled = false;
      	sendBtn.disabled = false;
      	conversationControls.show();
      }
      else if(message.type === "agent_state") {
      	const state = message.data;

      	if(state === "start"){
      		onAgentStarted();
      	}
      	else if(state === "stop") {
      		onAgentStopped();
      	}
      }
      else if(message.type === "new_conversation"){
      	const conversationId = message.conversationId;
      	const title = message.title;

      	conversations.unshift({
      		"id": conversationId,
      		"title": title
      	})

      	onNewConversationReceived(conversationId, title, true);

      }
      else if(message.type === "conversation_list") {
      	const conversationList = message.data;
      	onConversationListReceived(conversationList); 
      }
      else if (message.type === "get_conversation") {
      	const id = message.data.conversationId;
      	const messages = message.data.messages;
      	current_steps = onConversationReceived(id, messages);
      	//current_step_index = Math.max(0, current_steps.length);

      }
      else if(message.type === "conversation_deleted") {
      	const id = message.data;
      	onConversationDelete(id);

      }
      else if(message.type === "download_attachment") {
      	//console.log(message.base64, message.mimeType);
      	downloadBase64File(message.base64, message.mimeType, message.fileName, true);

      }
    } catch (err) {
      console.error('Error processing message:', err);
    }
  };

  ws.onerror = function(err) {
    status.textContent = 'Error';
    console.error('WebSocket error:', err);
    ss_status.innerText = "Error...";
    resizeTimeout = null;
    indicator.style.backgroundColor="red";
  };

  ws.onclose = function() {
    status.textContent = 'Disconnected';
    console.warn('WebSocket closed');
    img.hide();
    ss_status.show();
    ss_status.innerText = "Not connected...";
    ws = null;
    deviceSelect.innerHTML = '<option value="">Select a device</option>';
    resizeTimeout = null;
    //startRetrying();
    deviceControlButtons.hide();
    indicator.style.backgroundColor="red";
    chatInput.disabled = true;
  	sendBtn.disabled = true;
  	agentStateBtn.hide();
  	messages.innerHTML = "";
  	showView("main")
  	conversationControls.hide();
  };
}

function downloadBase64File(contentBase64, mimeType, fileName, openNewTab=false) {
	const linkSource = `data:${mimeType};base64,${contentBase64}`;
    
	if(openNewTab){
		console.log(mimeType);
		const byteCharacters = atob(contentBase64);
	    let byteNumbers = new Array(byteCharacters.length);
	    for (var i = 0; i < byteCharacters.length; i++) {
	        byteNumbers[i] = byteCharacters.charCodeAt(i);
	    }
	    var byteArray = new Uint8Array(byteNumbers);
	    var file = new Blob([byteArray], { type: mimeType + ';base64' });
	    var fileURL = URL.createObjectURL(file);
	    window.open(fileURL);
	}
	else {
		const downloadLink = document.createElement('a');
	    document.body.appendChild(downloadLink);

	    downloadLink.href = linkSource;
	    downloadLink.target = '_self';
	    downloadLink.download = fileName;
	    downloadLink.click(); 
	}
    
}

function onDeviceListReceived(devices) {
	console.log(devices)

	deviceSelect.innerHTML = '<option value="">Select a device</option>'; // Reset options

	devices.forEach((device, index) => {
		console.log(device, index)
		const option = document.createElement('option');
		option.value = index;
		option.textContent = device || `Device ${index + 1}`;
		deviceSelect.appendChild(option);
	});

	if(devices.length > 0) {
		deviceSelect.value = 0;
		current_device_selected = devices[0];
	}

	refreshDeviceBtn.disabled = false;
}

function onDeviceConnected(device) {
	console.log("Connected to device", device);
  	connectDeviceBtn.disabled = false;
  	ss_status.hide();
  	img.show();
  	deviceControlButtons.show();
}

function onConnectButtonPressed() {
	deviceControlButtons.hide();
	
	if(current_device_selected) {
		if(ws && ws.readyState === WebSocket.OPEN) {	
			ws.send(JSON.stringify({
				type: "connect_to_device",
				data: current_device_selected
			}))
		}
	}
	else {
		alert("Please select a device");
	}
}

function onToolResultReceived(toolResult){

}

deviceSelect.addEventListener('change', () => {
  const selectedIndex = deviceSelect.value;
  current_device_selected = selectedIndex !== '' ? devices[selectedIndex] : null;
});

connectDeviceBtn.addEventListener('click', () => {
  if (current_device_selected) {
  	if (ws && ws.readyState === WebSocket.OPEN) {
	  ws.send(JSON.stringify({
	      type: "connect_to_device",
    	  data: current_device_selected
	  }));
	  connectDeviceBtn.disabled = true;
	  ss_status.show();
	  ss_status.innerText = "Connecting...";
	  img.hide();
	  conversationControls.hide();
  	} 
  }
  else {
      alert("Please select a device.");
  }
});

refreshDeviceBtn.addEventListener('click', () => {
  if (ws && ws.readyState === WebSocket.OPEN) {
	refreshDeviceBtn.disabled = true;
	ws.send(JSON.stringify({
	  type: "list_devices"
	}));
  }
});

function startRetrying() {
  if (!retryTimer) {
    retryTimer = setInterval(() => {
      console.log('Attempting to reconnect WebSocket...');
      connectWebSocket();
    }, retryInterval);
  }
}

connectWebSocket();

let typedString = '';
let debounceDelay = 300;
let debounceTimeout;
let canSendInput = true;

document.addEventListener('keydown', (e) => {
    if (!isFocused) return;


    clearTimeout(debounceTimeout);

    if (e.key.length === 1) {
        typedString += e.key;
        canSendInput = false;
        debounceTimeout = setTimeout(() => {
            console.log('Typed string:', typedString);
            if(ws && ws.readyState === WebSocket.OPEN) {
            	ws.send(JSON.stringify({
            		type: "input",
            		data: typedString
            	}))
            }
            typedString = '';
            canSendInput = true 
        }, debounceDelay);
    }
    else {
    	if ((e.keyCode === 13 || e.keyCode === 8) && canSendInput) {
    		if(ws && ws.readyState === WebSocket.OPEN) {
            	ws.send(JSON.stringify({
            		type: "input",
            		data: e.keyCode
            	}))
            }
    	}
    	console.log(e.keyCode);
    }
});

function addMessage(text, sender = 'user') {
	const msg = document.createElement('div');
	msg.className = 'message ' + sender;

	if(sender === 'user' || sender === 'info') {
		msg.textContent  = text;
	}
	else {
		const test = marked.parse(text);
		msg.innerHTML = test;
	}
	messages.appendChild(msg);
	messages.scrollTop = messages.scrollHeight;
	return msg;
}

function sendMessage() {
	const text = chatInput.value;
	if (text !== '') {
		addMessage(text, 'user');
		
		if(ws && ws.readyState == WebSocket.OPEN) {
			ws.send(JSON.stringify({
				type: "message",
				data: text
			}))

			console.log("okay")
		}

		chatInput.value = '';
		resizeInput();
	}
}

sendBtn.addEventListener('click', sendMessage);


function onAgentStopped() {

	const runAgentIconSVG = `
	  <svg style="margin-left: 2px;" class="icon-sm" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 512">
	  <!--!Font Awesome Free 6.7.2 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2025 Fonticons, Inc.--><path d="M73 39c-14.8-9.1-33.4-9.4-48.5-.9S0 62.6 0 80L0 432c0 17.4 9.4 33.4 24.5 41.9s33.7 8.1 48.5-.9L361 297c14.3-8.7 23-24.2 23-41s-8.7-32.2-23-41L73 39z"/>
	  </svg>
	`;
	
	const wrapper = agentStateBtn.querySelector("#icon-wrapper");
	wrapper.innerHTML = runAgentIconSVG;
	
	agentStateBtn.setAttribute("data-state", "start");
	agentStateBtn.setAttribute("data-tooltip", "Start Agent");
	agentStateBtn.classList.remove("loading");
	agentStateBtn.disabled = false;
	//newChatBtn.disabled = false;
	sendBtn.disabled = false;
	chatInput.disabled = false;
}

function onAgentStarted() {
	
	
	const stopAgentIconSVG = `
	  <svg class="icon-sm" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 512">
	  <!--!Font Awesome Free 6.7.2 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2025 Fonticons, Inc.--><path d="M0 128C0 92.7 28.7 64 64 64H320c35.3 0 64 28.7 64 64V384c0 35.3-28.7 64-64 64H64c-35.3 0-64-28.7-64-64V128z"/>
	  </svg>
	`;

	agentStateBtn.classList.add('loading');
	const wrapper = agentStateBtn.querySelector("#icon-wrapper");
	wrapper.innerHTML = stopAgentIconSVG;	

	agentStateBtn.setAttribute("data-state", "stop");
	agentStateBtn.setAttribute("data-tooltip", "Stop Agent");
	agentStateBtn.disabled = false;
	sendBtn.disabled = false;
	chatInput.disabled = false;
	//newChatBtn.disabled = false;

	if(agentStateBtn.classList.contains("hidden")) {
		agentStateBtn.show();
	}

}

function onAgentStateBtnClicked(e) {
	e.preventDefault();
	const self = e.currentTarget;
	const state = self.getAttribute("data-state");
	self.disabled = true;
	sendBtn.disabled = true;
	chatInput.disabled = true;
	//newChatBtn.disabled = true;
	
	self.classList.remove("loading");

	if(ws && ws.readyState === WebSocket.OPEN){
		ws.send(JSON.stringify({
			"type": "agent_state",
			"data": state
		}))
	}

}

agentStateBtn.addEventListener('click', onAgentStateBtnClicked);

function onNewChat() {
	showView("main");
	agentStateBtn.hide();
	messages.innerHTML = "";
	const activeElements = conversationListBody.querySelectorAll(".conversation.active");
	activeElements.forEach(el => el.classList.remove("active"));
  	//current_step_index = 0;
  	current_steps = [];
}

function onNewChatButtonClicked(e) {
	e.preventDefault();

	onNewChat();

	if(ws && ws.readyState === WebSocket.OPEN) {
		ws.send(JSON.stringify({
			"type": "new_chat"
		}))
	}
}

newChatBtn.addEventListener('click', onNewChatButtonClicked);

function startTakeControl(e) {
	e.preventDefault();
	const self = e.currentTarget;
	const hasControl = self.getAttribute("has-control") === "true";

	if(ws && ws.readyState === WebSocket.OPEN) {
		ws.send(JSON.stringify({
			type: "control",
			data: hasControl ? "release" : "take"
		}))
	}
	//const wrapper = self.querySelector("#icon-wrapper");
	//wrapper.innerHTML = stopControlIconSVG;
	self.classList.add("loading");
	self.disabled = true;

	if(hasControl)
		screenshot.style.pointerEvents = "none";
}

function endTakeControl(success) {

	const takeControlIconSVG = `
	  <svg class="icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
	  <!--!Font Awesome Free 6.7.2 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2025 Fonticons, Inc.--><path d="M288 32c0-17.7-14.3-32-32-32s-32 14.3-32 32l0 208c0 8.8-7.2 16-16 16s-16-7.2-16-16l0-176c0-17.7-14.3-32-32-32s-32 14.3-32 32l0 272c0 1.5 0 3.1 .1 4.6L67.6 283c-16-15.2-41.3-14.6-56.6 1.4s-14.6 41.3 1.4 56.6L124.8 448c43.1 41.1 100.4 64 160 64l19.2 0c97.2 0 176-78.8 176-176l0-208c0-17.7-14.3-32-32-32s-32 14.3-32 32l0 112c0 8.8-7.2 16-16 16s-16-7.2-16-16l0-176c0-17.7-14.3-32-32-32s-32 14.3-32 32l0 176c0 8.8-7.2 16-16 16s-16-7.2-16-16l0-208z"/>
	  </svg>
	`;

	const stopControlIconSVG = `
	  <svg class="icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 512">
	  <!--!Font Awesome Free 6.7.2 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2025 Fonticons, Inc.--><path d="M0 128C0 92.7 28.7 64 64 64H320c35.3 0 64 28.7 64 64V384c0 35.3-28.7 64-64 64H64c-35.3 0-64-28.7-64-64V128z"/>
	  </svg>
	`;

	takeControlButton.classList.remove('loading');
	takeControlButton.disabled = false;
	const hasControl = takeControlButton.getAttribute('has-control') === "true";
	
	const wrapper = takeControlButton.querySelector("#icon-wrapper");

	if(success) {
		takeControlButton.setAttribute("data-tooltip", hasControl ? "Take Control" : "Release Control")
		takeControlButton.setAttribute("has-control", !hasControl)
		wrapper.innerHTML = hasControl ? takeControlIconSVG : stopControlIconSVG;
		screenshot.style.pointerEvents = hasControl ? "none" : "all";
	}
	else {
		wrapper.innerHTML = hasControl ? stopControlIconSVG : takeControlIconSVG;
	}
}


takeControlButton.addEventListener('click', startTakeControl);


chatInput.addEventListener('keydown', (e) => {
	if (e.key === 'Enter' && !e.shiftKey) {
		e.preventDefault();
		sendMessage();
	}
});

chatInput.addEventListener('input', resizeInput);

function resizeInput() {
	chatInput.style.height = '42px';
	chatInput.style.height = Math.min(chatInput.scrollHeight - 2, 180) + 'px';
	
	if(chatInput.scrollHeight >= 180) {
		chatInput.style.overflowY = 'auto'
	}
	else {
		chatInput.style.overflowY = 'hidden'
	}
}


/*modalClose.addEventListener('click', () => {
  	modal.hide()
});*/

window.addEventListener('click', (e) => {
	if (e.target === modal) {
		selectedConversation = "";
		modal.hide()
	}
});


function showView(id, toolResult=undefined) {
	const leftContainer = document.getElementById("left");
	
	showMainBtn.show();
	let result = null;
	for (const child of leftContainer.children) {
	  
	  if(child.id !== "conversation-list-container" && child.id !== "showMainBtn")
	  	child.hide();
	  
	  if(child.id === id) {
	  	if(id === "main"){
	  		showMainBtn.hide();
	  	}
	  	child.show();
	  	result = child;
	  }
	}

	return result;
}




function onConversationDeleteBtnClicked(id, title){
	selectedConversation = id;
	const modalConvoName = modalOutput.querySelector("#modal-conversation-name")
	modalConvoName.innerText = title;
	modal.show();

}

function onModalDeleteBtnClicked() {
	/*if(selectedConversation !== ""){
		onConversationDelete(selectedConversation);
	}
*/
	modal.hide();

	if(ws && ws.readyState === WebSocket.OPEN){
		ws.send(JSON.stringify({
			"type": "delete_conversation",
			"id": selectedConversation
		}))
	}
}

modalDeleteBtn.addEventListener('click', onModalDeleteBtnClicked)


modalCancelBtn.addEventListener('click', () => {
	selectedConversation = "";
	modal.hide();
})

showMainBtn.addEventListener('click', () => {
	showView("main");
})

function onConversationClicked(actions, id){
	
	showView("main");
	const convo = actions.parentElement;
	const spinner = actions.querySelector(".spinner-convo");
	const deleteBtn = actions.querySelector(".icon-button");

	const activeElements = conversationListBody.querySelectorAll(".conversation.active");
	activeElements.forEach(el => el.classList.remove("active"));

	spinner.show();
	deleteBtn.hide();
	sidebar.setAttribute("disabled", "")
	convo.classList.add("active")
	agentStateBtn.show();
	onAgentStopped();

	if(ws && ws.readyState === WebSocket.OPEN) {
		ws.send(JSON.stringify({
			"type": "get_conversation",
			"data": id
		}))
	}

}

function onConversationListReceived(conversationList){
	conversations = conversationList;
	conversationListBody.innerHTML = "";

	conversationList.forEach(convo => onNewConversationReceived(convo.id, convo.title))
}

function onConversationDelete(id){



	for (let i = conversations.length - 1; i >= 0; i--) {
		if (conversations[i].id === id) {
			conversations.splice(i, 1);
			break;
		}
	}

	const conv = conversationListBody.querySelector(`.conversation[data-id="${id}"]`);

	if(conv){
		conv.remove();
		if(currentConversation === selectedConversation) {
			onNewChat();
			currentConversation = "";
			showView("main");
		}
	}
	else {
		console.error(`Conversation ${id} does not exists.`)
	}

	selectedConversation = "";
	//current_step_index = 0;
	current_steps = [];
}

 messages.addEventListener('click', (e) => {
 	const toolButton = e.target.closest(".tool-button");
 	const attachmentButton = e.target.closest(".attachment");
 	if (toolButton) {
		const step_i = parseInt(toolButton.getAttribute('data-step'));
		const step = current_steps[step_i];
		
		const action = step.tool.action;
		const args = step.tool.parameters;
		const toolResult = step.result;

		onToolButtonPressed(action, args, toolResult);
	}

	if(attachmentButton) {

		const filePath = attachmentButton.getAttribute("data-file");
		if(filePath){
			if(ws && ws.readyState === WebSocket.OPEN) {
				console.log("DOWNLOAD ATTACHEMNT", filePath);
				ws.send(JSON.stringify({
					"type": "download_attachment",
					"data": filePath
				}))
			}
		}
	}

});


function onToolButtonPressed(action, args, toolResult){
	if(action === "file_write" || action === "file_read") {
		const view = showView("file");
		const file_path_element = view.querySelector("#file_path");
		const file_content_element = view.querySelector("#file_content");
		const filePath = args["file"];
		const fileName = filePath.split('/').pop();
		const fileNameExtension = fileName.split(".")[1];
		
		file_content_element.removeAttribute("class");
		file_content_element.removeAttribute("data-highlighted");
			
		file_path_element.innerText = fileName;

		if(fileNameExtension === "md"){
			file_content_element.innerHTML = marked.parse(toolResult);
		}
		else {
			file_content_element.textContent = toolResult;
			
			if(fileNameExtension !== "txt"){
				hljs.highlightElement(file_content_element);
			}
		}

	}
	else if (action === "shell_exec"){
		const view = showView("shell");
		const shellInput = view.querySelector(".shell-input")
		const shellOutput = view.querySelector(".shell-output")
		shellInput.innerText = `${args["exec_dir"]} >> ${args["command"]}`;
		shellOutput.innerText = toolResult;
	}
	else {
		showView("main");
	}
}

function getToolHtml(obj, step_index, addSpinner=false){
	//const data = JSON.parse(obj.content);

  	const action = obj.action;
  	const args = obj.parameters;

  	if(action !== 'message_notify_user' && action !== 'message_ask_user'){
  		let firstValue = ""

  		if(args){
	  		const keys = Object.keys(args)


	  		if (Object.keys(args).length > 0) {

					if(action.startsWith("file_")){
						firstValue = args["file"];
						firstValue = firstValue.split('/').pop();
					}
					else if(action === "shell_exec"){
						firstValue = args["command"];
					}
					else if(action === "swipe") {
						firstValue = args["direction"];
					}
					else if(action === "click") {
						if(args["coordinate_x"] && args["coordinate_y"])
							firstValue = args["coordinate_x"] + ", " + args["coordinate_y"];
						else
							firstValue = args["index"];
					}
					else if(action === "wait_for_seconds") {
						firstValue = args["seconds"] + " seconds";
					}
					else if(action === "create_project_folder"){
						firstValue = args["project_name"];
					}

	  		}
  		}

  		const test = addSpinner ? '<div class="spinner-small"></div>' : ""
      	let toolHtml = `<div><div class='tool-button' data-tool='${action}' data-step='${step_index}'>${test}<span id="mark" class=""></span><span class="command">${action}</span><span class="firstArg">${firstValue}</span></div></div>`;
      	if(action === "idle" && args.attachments) {
      		if(args.attachments.length > 0) {
      			toolHtml += '<div class="attachment-list">'
      			toolHtml += '<span class="attachment-title">Attachments</span>'
      			args.attachments.forEach(file => {
      				toolHtml += `<div class="attachment" data-file="${file}">
      					<svg class="icon-sm" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 512"><!--!Font Awesome Free 6.7.2 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2025 Fonticons, Inc.--><path d="M320 464c8.8 0 16-7.2 16-16l0-288-80 0c-17.7 0-32-14.3-32-32l0-80L64 48c-8.8 0-16 7.2-16 16l0 384c0 8.8 7.2 16 16 16l256 0zM0 64C0 28.7 28.7 0 64 0L229.5 0c17 0 33.3 6.7 45.3 18.7l90.5 90.5c12 12 18.7 28.3 18.7 45.3L384 448c0 35.3-28.7 64-64 64L64 512c-35.3 0-64-28.7-64-64L0 64z"/>
      					</svg>
      					<span>${file}</span>
      				</div>`
      			})
      			toolHtml += "</div>"
      		}
      	}

      	return toolHtml;
  	}
  	else {
  		if(action === 'message_ask_user'){
  			const result = `<div class="question">
  			<div class="question-badge">Question</div>
  			<span>${args["text"]}</span>
  			</div>`;

  			return result
  		}
  		return marked.parse(args["text"]);
  	}
}

function fixMark(result, lastElement){

  	const toolResult = result;
  	
  	const crossEmoji = "&#10060;"
  	const checkmarkEmoji="&#10004;&#65039;"

  	const mark = lastElement.querySelector("#mark");

  	if(mark){
  		if(toolResult){
	      	if (toolResult.startsWith("Error:")){
	      		mark.innerHTML = crossEmoji;
	      	}
	      	else {
	      		mark.innerHTML = checkmarkEmoji;
	      	}
      	}
  	}
}

function onConversationReceived(id, convoMessages) {

	currentConversation = id;
	messages.innerHTML = "";

	const convoElement = conversationListBody.querySelector(`.conversation[data-id="${id}"]`);

	if(convoElement) {
		const actions = convoElement.querySelector(".conversation-actions");
		const spinner = actions.querySelector(".spinner-convo");
		const deleteBtn = actions.querySelector(".icon-button");

		spinner.hide();
		deleteBtn.show();
		sidebar.removeAttribute("disabled");
	}
	
	let steps = [];
	let i = 0;

	convoMessages.forEach((message, index) => {

		if(message.role === "user") {
			addMessage(message.content, "user");
		}
		else if(message.role === "tool") {
			steps.push({
				"tool": JSON.parse(message.content),
				"result": ""
			})			
			const content = getToolHtml(JSON.parse(message.content), i);
			addMessage(content, "assistant")
		}
		else if(message.role === "function") {
			steps[i].result = message.content;
			const lastTool = messages.lastChild;
			fixMark(message.content, lastTool);
			i += 1;
		}
	})

	//current_step_index = i;

	return steps;
}

function onNewConversationReceived(id, title, setActive=false){
	const template = `
	<div class="conversation" data-id=${id}>
		<span title="${title}" class="conversation-title">${title}</span>
		<div class="conversation-actions">
			<div class="hidden spinner-convo"></div>
			<button class="icon-button bg-transparent no-hover-bg" data-size="xs" title="Delete Conversation">
				<svg style="margin-top:2px;" class="icon-xs deleteBtn" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 448 512"><!--!Font Awesome Free 6.7.2 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2025 Fonticons, Inc.--><path d="M135.2 17.7L128 32 32 32C14.3 32 0 46.3 0 64S14.3 96 32 96l384 0c17.7 0 32-14.3 32-32s-14.3-32-32-32l-96 0-7.2-14.3C307.4 6.8 296.3 0 284.2 0L163.8 0c-12.1 0-23.2 6.8-28.6 17.7zM416 128L32 128 53.2 467c1.6 25.3 22.6 45 47.9 45l245.8 0c25.3 0 46.3-19.7 47.9-45L416 128z"/></svg>
			</button>
		</div>
	</div>
	`
	
	const activeElements = conversationListBody.querySelectorAll(".conversation.active");
	activeElements.forEach(el => el.classList.remove("active"));

	conversationListBody.insertAdjacentHTML("afterbegin", template);

	const newConv = conversationListBody.querySelector(`.conversation[data-id="${id}"]`);
	if(setActive){
		currentConversation = id;
		newConv.classList.add("active")
	}
	const button = newConv.querySelector(".icon-button");
	const titleElement = newConv.querySelector(".conversation-title");
	const actions = newConv.querySelector(".conversation-actions")

	titleElement.addEventListener("click", () => onConversationClicked(actions, id));
	button.addEventListener("click", () => onConversationDeleteBtnClicked(id, title));
}

