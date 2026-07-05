// DOM Elements
const wsStatusPill = document.getElementById('ws-status-pill');
const listenerStatusPill = document.getElementById('listener-status-pill');
const activeLlmPill = document.getElementById('active-llm-pill');
const devicesContainer = document.getElementById('devices-container');
const voiceWaveContainer = document.getElementById('voice-wave-container');
const liveTranscriptText = document.getElementById('live-transcript-text');
const simInput = document.getElementById('sim-input');
const btnSimSend = document.getElementById('btn-sim-send');
const logListContainer = document.getElementById('log-list-container');

// Modal: Add Device
const btnAddDevice = document.getElementById('btn-add-device');
const addDeviceModal = document.getElementById('add-device-modal');
const addDeviceForm = document.getElementById('add-device-form');

// Modal: Settings & LLM Manager
const btnOpenSettings = document.getElementById('btn-open-settings');
const settingsModal = document.getElementById('settings-modal');
const ollamaStatusContainer = document.getElementById('ollama-status-container');
const modelsListContainer = document.getElementById('models-list-container');

// State
let socket = null;
let devices = {};
let voiceLogs = [];
let localModels = []; // Installed models on Ollama
let llmState = {
    binary_installed: false,
    service_running: false,
    status: 'Not Installed',
    install_percent: 0,
    active_model: null,
    pulling_model: null,
    pull_percent: 0
};
const apiBase = `${window.location.protocol}//${window.location.host}`;

// Target Models configuration
const PRECONFIGURED_MODELS = [
    {
        tag: 'gemma3:1b',
        displayName: 'Gemma 3 1B',
        size: 'approx. 800 MB',
        desc: "Google's ultra-lightweight and highly efficient model, perfect for micro-devices and quick local tasks."
    },
    {
        tag: 'qwen2.5:1.5b',
        displayName: 'Qwen 2.5 1.5B',
        size: 'approx. 900 MB',
        desc: "Alibaba's advanced small language model, offering exceptional language understanding and JSON formatting."
    },
    {
        tag: 'tinyllama:1.1b',
        displayName: 'TinyLlama 1.1B',
        size: 'approx. 600 MB',
        desc: "A compact 1.1B model pre-trained on 3 trillion tokens, designed for extreme speed and low memory footprints."
    }
];

// ----------------- WebSocket Connection -----------------

function connectWebSocket() {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws`;
    
    updateWsStatus('connecting', 'Connecting...');
    
    socket = new WebSocket(wsUrl);
    
    socket.onopen = () => {
        updateWsStatus('online', 'Server: Online');
        console.log('Connected to WebSocket server');
    };
    
    socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        console.log('Received WebSocket message:', message);
        
        switch (message.type) {
            case 'init':
                devices = message.data.devices;
                voiceLogs = message.data.voice_logs;
                updateVoiceListenerStatus(message.data.listener_status);
                
                if (message.data.llm) {
                    llmState = message.data.llm;
                    updateLlmPill(llmState.active_model);
                    refreshLLMSettingsUI();
                }
                
                renderDevices();
                renderVoiceLogs();
                break;
            case 'devices':
                devices = message.data;
                renderDevices();
                break;
            case 'voice_log':
                voiceLogs.unshift(message.data);
                if (voiceLogs.length > 50) voiceLogs.pop();
                renderVoiceLogs();
                triggerVisualCommandAlert(message.data);
                break;
            case 'listener_status':
                updateVoiceListenerStatus(message.data);
                break;
            case 'ollama_install':
                llmState.status = message.data.status;
                if (message.data.percent !== undefined) {
                    llmState.install_percent = message.data.percent;
                }
                llmState.install_speed = message.data.speed || "";
                llmState.install_eta = message.data.eta || "";
                if (llmState.status === 'Running') {
                    llmState.service_running = true;
                    llmState.binary_installed = true;
                    fetchLLMData();
                }
                renderOllamaStatus();
                break;
            case 'model_pull':
                if (message.data.status === 'downloading') {
                    llmState.pulling_model = message.data.model;
                    llmState.pull_percent = message.data.percent;
                    llmState.pull_speed = message.data.speed || "";
                    llmState.pull_eta = message.data.eta || "";
                } else if (message.data.status === 'success') {
                    llmState.pulling_model = null;
                    llmState.pull_percent = 0;
                    llmState.pull_speed = "";
                    llmState.pull_eta = "";
                    if (message.data.active_model) {
                        llmState.active_model = message.data.active_model;
                    }
                    fetchLLMData(); // Refresh list
                } else if (message.data.status === 'failed') {
                    alert(`Failed to pull model: ${message.data.error}`);
                    llmState.pulling_model = null;
                    llmState.pull_percent = 0;
                    llmState.pull_speed = "";
                    llmState.pull_eta = "";
                    fetchLLMData();
                }
                updateLlmPill(llmState.active_model);
                renderModelsList();
                break;
            case 'model_deleted':
                if (llmState.active_model === message.data.model) {
                    llmState.active_model = null;
                }
                fetchLLMData();
                break;
            case 'model_switched':
                llmState.active_model = message.data.active_model;
                updateLlmPill(llmState.active_model);
                renderModelsList();
                break;
            default:
                break;
        }
    };
    
    socket.onclose = () => {
        updateWsStatus('offline', 'Server: Offline');
        updateVoiceListenerStatus('Stopped');
        setTimeout(connectWebSocket, 3000);
    };
}

function updateWsStatus(status, text) {
    const indicator = wsStatusPill.querySelector('.pulse-indicator');
    const label = wsStatusPill.querySelector('.status-label');
    
    label.textContent = text;
    indicator.className = 'pulse-indicator';
    
    if (status === 'online') {
        indicator.classList.add('green');
    } else if (status === 'connecting') {
        indicator.classList.add('orange');
    } else {
        indicator.classList.add('red');
    }
}

function updateVoiceListenerStatus(status) {
    const indicator = listenerStatusPill.querySelector('.pulse-indicator');
    const label = listenerStatusPill.querySelector('.status-label');
    
    label.textContent = `Voice: ${status}`;
    indicator.className = 'pulse-indicator';
    
    if (status === 'Listening') {
        indicator.classList.add('green');
        voiceWaveContainer.classList.add('listening');
        liveTranscriptText.textContent = "Listening for voice command...";
    } else if (status.startsWith('Simulation')) {
        indicator.classList.add('green');
        voiceWaveContainer.classList.remove('listening');
        liveTranscriptText.textContent = "Ready (Simulation Mode)";
    } else if (status.startsWith('Error')) {
        indicator.classList.add('red');
        voiceWaveContainer.classList.remove('listening');
        liveTranscriptText.textContent = status;
    } else {
        indicator.classList.add('orange');
        voiceWaveContainer.classList.remove('listening');
        liveTranscriptText.textContent = "Voice engine idle";
    }
}

function updateLlmPill(activeModel) {
    const label = activeLlmPill.querySelector('.status-label');
    if (activeModel) {
        label.textContent = `LLM: ${activeModel.split(':')[0]}`;
        activeLlmPill.style.color = 'var(--primary)';
        activeLlmPill.style.borderColor = 'rgba(0, 240, 255, 0.2)';
    } else {
        label.textContent = 'LLM: Rule-based';
        activeLlmPill.style.color = 'var(--text-muted)';
        activeLlmPill.style.borderColor = 'var(--glass-border)';
    }
}

// ----------------- Rendering Dashboard -----------------

function renderDevices() {
    devicesContainer.innerHTML = '';
    
    const deviceIds = Object.keys(devices);
    
    if (deviceIds.length === 0) {
        devicesContainer.innerHTML = `
            <div class="loading-state">
                <i class="fa-solid fa-circle-info"></i>
                <p>No devices registered. Click "Add Device" to add an ESP module.</p>
            </div>
        `;
        return;
    }
    
    deviceIds.forEach(id => {
        const device = devices[id];
        const isActive = device.state === 'on';
        const isOnline = device.online;
        
        let iconClass = 'fa-solid fa-power-off';
        if (device.type === 'smart_plug') iconClass = 'fa-solid fa-plug';
        if (device.type === 'rgb_led') iconClass = 'fa-solid fa-lightbulb';
        
        const card = document.createElement('div');
        card.className = `device-card ${isActive ? 'device-active' : ''}`;
        card.innerHTML = `
            <button class="btn-delete-device" onclick="deleteDevice('${id}')">
                <i class="fa-solid fa-trash"></i>
            </button>
            <div class="device-info">
                <div class="device-name-ip">
                    <h3>${escapeHtml(device.name)}</h3>
                    <span class="device-ip">${escapeHtml(device.ip)}</span>
                </div>
                <div class="device-icon-box">
                    <i class="${iconClass}"></i>
                </div>
            </div>
            <div class="device-card-footer">
                <div class="device-status">
                    <span class="pulse-indicator ${isOnline ? 'green' : 'red'}"></span>
                    <span class="status-text ${isOnline ? 'online' : 'offline'}">
                        ${isOnline ? 'Online' : 'Offline (Sim)'}
                    </span>
                </div>
                <label class="switch">
                    <input type="checkbox" ${isActive ? 'checked' : ''} onchange="toggleDevice('${id}', this.checked)">
                    <span class="slider"></span>
                </label>
            </div>
        `;
        devicesContainer.appendChild(card);
    });
}

function renderVoiceLogs() {
    logListContainer.innerHTML = '';
    
    if (voiceLogs.length === 0) {
        logListContainer.innerHTML = `
            <div class="empty-logs">
                <i class="fa-solid fa-list-check"></i>
                <p>No voice commands captured yet.</p>
            </div>
        `;
        return;
    }
    
    voiceLogs.forEach(log => {
        const isSuccess = log.status.startsWith('Success');
        const item = document.createElement('div');
        item.className = 'log-item';
        item.innerHTML = `
            <div class="log-content">
                <span class="log-phrase">"${escapeHtml(log.phrase)}"</span>
                <span class="log-intent">${escapeHtml(log.intent)}</span>
            </div>
            <span class="log-badge ${isSuccess ? 'success' : 'fail'}">${escapeHtml(log.status)}</span>
        `;
        logListContainer.appendChild(item);
    });
}

function triggerVisualCommandAlert(log) {
    liveTranscriptText.textContent = `"${log.phrase}"`;
    
    if (log.status.startsWith('Success')) {
        liveTranscriptText.style.color = 'var(--primary)';
        setTimeout(() => {
            liveTranscriptText.style.color = '';
        }, 2000);
    } else {
        liveTranscriptText.style.color = 'var(--error)';
        setTimeout(() => {
            liveTranscriptText.style.color = '';
        }, 2000);
    }
}

// ----------------- Rendering LLM Settings Modal -----------------

function refreshLLMSettingsUI() {
    renderOllamaStatus();
    renderModelsList();
}

function renderOllamaStatus() {
    let healthText = '';
    let actionButtons = '';
    
    if (llmState.status === 'Running') {
        healthText = `<span class="text-success"><span class="pulse-indicator green" style="margin-right: 5px;"></span> Active & Running</span>`;
        actionButtons = `<span class="device-ip">Port: 11434 (Local)</span>`;
    } else if (llmState.status === 'Stopped') {
        healthText = `<span class="text-warning"><i class="fa-solid fa-circle-pause"></i> Stopped</span>`;
        actionButtons = `<button class="btn btn-secondary btn-sm" onclick="startOllamaService()">Start Service</button>`;
    } else if (llmState.status.startsWith('Downloading')) {
        const speedSuffix = llmState.install_speed ? ` @ ${llmState.install_speed}` : '';
        healthText = `<span class="text-warning"><i class="fa-solid fa-spinner fa-spin"></i> Downloading Binary...</span>`;
        actionButtons = `
            <div class="progress-wrapper" style="width: 100%;">
                <div class="progress-label-row">
                    <span>Downloading Ollama ARM64 package${speedSuffix}</span>
                    <span>${llmState.install_percent}%</span>
                </div>
                <div class="progress-bar-container">
                    <div class="progress-bar-fill" style="width: ${llmState.install_percent}%"></div>
                </div>
                <div class="progress-label-row" style="margin-top: 2px; font-size: 0.7rem; opacity: 0.85;">
                    <span>Time remaining: ${llmState.install_eta || 'Calculating...'}</span>
                </div>
            </div>
        `;
    } else if (llmState.status === 'Extracting') {
        healthText = `<span class="text-warning"><i class="fa-solid fa-spinner fa-spin"></i> Extracting Files...</span>`;
        actionButtons = `
            <div class="progress-wrapper" style="width: 100%;">
                <div class="progress-label-row">
                    <span>Unpacking files (tar & zstd)</span>
                    <span>Please wait...</span>
                </div>
                <div class="progress-bar-container">
                    <div class="progress-bar-fill" style="width: 100%"></div>
                </div>
            </div>
        `;
    } else if (llmState.status === 'Failed' || llmState.status === 'Failed to Start') {
        healthText = `<span class="text-error"><i class="fa-solid fa-triangle-exclamation"></i> Startup Failed</span>`;
        actionButtons = `<button class="btn btn-primary btn-sm" onclick="installOllamaService()">Retry Installation</button>`;
    } else { // Not Installed
        healthText = `<span class="text-muted"><i class="fa-solid fa-ban"></i> Not Installed</span>`;
        actionButtons = `<button class="btn btn-primary btn-sm" onclick="installOllamaService()"><i class="fa-solid fa-download"></i> Install Ollama (ARM64)</button>`;
    }
    
    ollamaStatusContainer.innerHTML = `
        <div class="status-row">
            <span class="status-label">Service Health:</span>
            <div class="status-val">${healthText}</div>
        </div>
        <div class="server-actions-row">
            ${actionButtons}
        </div>
    `;
}

function renderModelsList() {
    modelsListContainer.innerHTML = '';
    
    if (llmState.status !== 'Running') {
        modelsListContainer.innerHTML = `
            <div class="loading-state">
                <i class="fa-solid fa-server"></i>
                <p>Ollama server must be active and running to manage models.</p>
            </div>
        `;
        return;
    }
    
    PRECONFIGURED_MODELS.forEach(model => {
        // Check if model is downloaded
        const installed = localModels.some(m => m.name === model.tag || m.name.split(':')[0] === model.tag.split(':')[0]);
        const isActive = llmState.active_model && (llmState.active_model === model.tag || llmState.active_model.split(':')[0] === model.tag.split(':')[0]);
        const isPulling = llmState.pulling_model === model.tag;
        
        const card = document.createElement('div');
        card.className = `model-card-item ${isActive ? 'model-active' : ''}`;
        
        let actionMarkup = '';
        if (isPulling) {
            const speedSuffix = llmState.pull_speed ? ` @ ${llmState.pull_speed}` : '';
            actionMarkup = `
                <div class="progress-wrapper" style="min-width: 180px;">
                    <div class="progress-label-row">
                        <span>Pulling${speedSuffix}</span>
                        <span>${llmState.pull_percent}%</span>
                    </div>
                    <div class="progress-bar-container">
                        <div class="progress-bar-fill" style="width: ${llmState.pull_percent}%"></div>
                    </div>
                    <div class="progress-label-row" style="margin-top: 2px; font-size: 0.7rem; opacity: 0.85; justify-content: flex-start; gap: 4px;">
                        <span>Time remaining:</span>
                        <span>${llmState.pull_eta || 'Calculating...'}</span>
                    </div>
                </div>
            `;
        } else if (installed) {
            if (isActive) {
                actionMarkup = `
                    <span class="model-badge-active"><i class="fa-solid fa-check"></i> Active</span>
                    <button class="btn-icon" title="Remove Model" onclick="deleteModel('${model.tag}')">
                        <i class="fa-solid fa-trash-can"></i>
                    </button>
                `;
            } else {
                actionMarkup = `
                    <button class="btn btn-secondary btn-sm" onclick="switchModel('${model.tag}')">Activate</button>
                    <button class="btn-icon" title="Remove Model" onclick="deleteModel('${model.tag}')">
                        <i class="fa-solid fa-trash-can"></i>
                    </button>
                `;
            }
        } else {
            // Disable button if another pull is active
            const pullDisabled = llmState.pulling_model !== null;
            actionMarkup = `
                <button class="btn btn-primary btn-sm" ${pullDisabled ? 'disabled' : ''} onclick="pullModel('${model.tag}')">
                    <i class="fa-solid fa-download"></i> Pull (${model.size})
                </button>
            `;
        }
        
        card.innerHTML = `
            <div class="model-details">
                <div class="model-title-row">
                    <h5>${escapeHtml(model.displayName)}</h5>
                    <span class="model-size-tag">${escapeHtml(model.tag)}</span>
                </div>
                <p class="model-desc">${escapeHtml(model.desc)}</p>
            </div>
            <div class="model-actions">
                ${actionMarkup}
            </div>
        `;
        modelsListContainer.appendChild(card);
    });
}

// ----------------- API Calls: Devices -----------------

async function toggleDevice(id, state) {
    try {
        const response = await fetch(`${apiBase}/api/devices/${id}/toggle?state=${state}`, {
            method: 'POST'
        });
        if (!response.ok) throw new Error('Failed to toggle device');
        const data = await response.json();
        console.log('Toggled device status:', data);
    } catch (err) {
        console.error(err);
        renderDevices();
    }
}

async function deleteDevice(id) {
    if (!confirm(`Are you sure you want to delete the device "${devices[id].name}"?`)) return;
    
    try {
        const response = await fetch(`${apiBase}/api/devices/${id}`, {
            method: 'DELETE'
        });
        if (!response.ok) throw new Error('Failed to delete device');
        console.log('Deleted device:', id);
    } catch (err) {
        console.error(err);
    }
}

async function simulateVoiceCommand() {
    const text = simInput.value.trim();
    if (!text) return;
    
    simInput.value = '';
    liveTranscriptText.textContent = `Simulating: "${text}"`;
    
    try {
        const response = await fetch(`${apiBase}/api/simulate-voice?command=${encodeURIComponent(text)}`, {
            method: 'POST'
        });
        if (!response.ok) throw new Error('Simulation failed');
    } catch (err) {
        console.error(err);
        liveTranscriptText.textContent = "Simulation failed";
    }
}

// ----------------- API Calls: Local LLM -----------------

async function fetchLLMData() {
    try {
        // Fetch health status
        const statusRes = await fetch(`${apiBase}/api/llm/status`);
        if (statusRes.ok) {
            llmState = await statusRes.json();
            updateLlmPill(llmState.active_model);
        }
        
        // Fetch model list
        if (llmState.service_running) {
            const modelsRes = await fetch(`${apiBase}/api/llm/models`);
            if (modelsRes.ok) {
                localModels = await modelsRes.json();
            }
        } else {
            localModels = [];
        }
        
        refreshLLMSettingsUI();
    } catch (err) {
        console.error('Error fetching LLM data:', err);
    }
}

async function installOllamaService() {
    try {
        const btn = document.querySelector('.server-actions-row button');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Triggering Install...`;
        }
        
        const response = await fetch(`${apiBase}/api/llm/install`, { method: 'POST' });
        if (!response.ok) throw new Error('Failed to trigger installation');
        const data = await response.json();
        console.log('Installation triggered:', data);
        
        // Instantly transition to downloading state in UI to avoid latency confusion
        llmState.status = 'Downloading 0%';
        llmState.install_percent = 0;
        renderOllamaStatus();
        
        // Wait 1.5 seconds before fetching status to allow backend thread to set up
        setTimeout(fetchLLMData, 1500);
    } catch (err) {
        alert(`Error starting install: ${err.message}`);
        fetchLLMData();
    }
}

async function startOllamaService() {
    try {
        const response = await fetch(`${apiBase}/api/llm/start`, { method: 'POST' });
        if (!response.ok) throw new Error('Failed to start service');
        const data = await response.json();
        console.log('Service started:', data);
        fetchLLMData();
    } catch (err) {
        alert(`Error starting service: ${err.message}`);
    }
}

async function pullModel(modelName) {
    try {
        const response = await fetch(`${apiBase}/api/llm/pull`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_name: modelName })
        });
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.detail || 'Failed to pull model');
        }
        console.log(`Pull started for: ${modelName}`);
        
        // Instantly show pulling state in UI
        llmState.pulling_model = modelName;
        llmState.pull_percent = 0;
        renderModelsList();
        
        setTimeout(fetchLLMData, 1500);
    } catch (err) {
        alert(err.message);
        fetchLLMData();
    }
}

async function deleteModel(modelName) {
    if (!confirm(`Are you sure you want to delete the model "${modelName}"? This will free up storage.`)) return;
    
    try {
        const response = await fetch(`${apiBase}/api/llm/models/${encodeURIComponent(modelName)}`, {
            method: 'DELETE'
        });
        if (!response.ok) throw new Error('Failed to delete model');
        console.log(`Deleted model: ${modelName}`);
        fetchLLMData();
    } catch (err) {
        alert(err.message);
    }
}

async function switchModel(modelName) {
    try {
        const response = await fetch(`${apiBase}/api/llm/switch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_name: modelName })
        });
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.detail || 'Failed to activate model');
        }
        console.log(`Switched to active model: ${modelName}`);
        fetchLLMData();
    } catch (err) {
        alert(err.message);
    }
}

// ----------------- Modals Toggles & Overlay Hooks -----------------

function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('active');
        if (modalId === 'settings-modal') {
            fetchLLMData();
        }
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('active');
        if (modalId === 'add-device-modal') {
            addDeviceForm.reset();
        }
    }
}

// Event Bindings
btnOpenSettings.addEventListener('click', () => openModal('settings-modal'));
btnAddDevice.addEventListener('click', () => openModal('add-device-modal'));

addDeviceForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const deviceId = document.getElementById('device-id').value.trim();
    const name = document.getElementById('device-name').value.trim();
    const ip = document.getElementById('device-ip').value.trim();
    const type = document.getElementById('device-type').value;
    
    try {
        const response = await fetch(`${apiBase}/api/devices?device_id=${encodeURIComponent(deviceId)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, ip, type })
        });
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || 'Failed to add device');
        }
        
        closeModal('add-device-modal');
    } catch (err) {
        alert(err.message);
    }
});

btnSimSend.addEventListener('click', simulateVoiceCommand);
simInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') simulateVoiceCommand();
});

// Helper
function escapeHtml(str) {
    if (typeof str !== 'string') return '';
    return str.replace(/&/g, "&amp;")
              .replace(/</g, "&lt;")
              .replace(/>/g, "&gt;")
              .replace(/"/g, "&quot;")
              .replace(/'/g, "&#039;");
}

// Initialize
connectWebSocket();
// Initial fetch of LLM settings
setTimeout(fetchLLMData, 1000);
