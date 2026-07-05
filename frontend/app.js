// DOM Elements
const wsStatusPill = document.getElementById('ws-status-pill');
const listenerStatusPill = document.getElementById('listener-status-pill');
const geminiStatusPill = document.getElementById('gemini-status-pill');
const devicesContainer = document.getElementById('devices-container');
const voiceWaveContainer = document.getElementById('voice-wave-container');
const liveTranscriptText = document.getElementById('live-transcript-text');
const simInput = document.getElementById('sim-input');
const btnSimSend = document.getElementById('btn-sim-send');
const logListContainer = document.getElementById('log-list-container');

// Modal Elements
const btnAddDevice = document.getElementById('btn-add-device');
const addDeviceModal = document.getElementById('add-device-modal');
const btnCloseModal = document.getElementById('btn-close-modal');
const btnCancelModal = document.getElementById('btn-cancel-modal');
const addDeviceForm = document.getElementById('add-device-form');

// State
let socket = null;
let devices = {};
let voiceLogs = [];
const apiBase = `${window.location.protocol}//${window.location.host}`;

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
                updateGeminiStatus(message.data.gemini_active);
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
            default:
                break;
        }
    };
    
    socket.onclose = () => {
        updateWsStatus('offline', 'Server: Offline');
        updateVoiceListenerStatus('Stopped');
        // Try to reconnect every 3 seconds
        setTimeout(connectWebSocket, 3000);
    };
    
    socket.onerror = (err) => {
        console.error('WebSocket error:', err);
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

function updateGeminiStatus(active) {
    const label = geminiStatusPill.querySelector('.status-label');
    if (active) {
        geminiStatusPill.classList.add('active');
        label.textContent = 'AI: Gemini 2.5';
        geminiStatusPill.style.color = 'var(--primary)';
        geminiStatusPill.style.borderColor = 'rgba(0, 240, 255, 0.2)';
    } else {
        geminiStatusPill.classList.remove('active');
        label.textContent = 'AI: Offline';
        geminiStatusPill.style.color = 'var(--text-muted)';
        geminiStatusPill.style.borderColor = 'var(--glass-border)';
    }
}

// ----------------- Rendering -----------------

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
        
        // Pick proper icon
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
        const isSuccess = log.status === 'Success';
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
    
    // Flash text green/cyan on success
    if (log.status === 'Success') {
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

// ----------------- Actions -----------------

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
        // Revert toggle visually if failed
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
        if (!response.ok) throw new Error('Simulation endpoint returned error');
    } catch (err) {
        console.error(err);
        liveTranscriptText.textContent = "Simulation failed";
    }
}

// ----------------- Modal Event Handlers -----------------

btnAddDevice.addEventListener('click', () => {
    addDeviceModal.classList.add('active');
    document.getElementById('device-id').focus();
});

function closeModal() {
    addDeviceModal.classList.remove('active');
    addDeviceForm.reset();
}

btnCloseModal.addEventListener('click', closeModal);
btnCancelModal.addEventListener('click', closeModal);

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
        
        closeModal();
    } catch (err) {
        alert(err.message);
    }
});

// Simulate voice on button or Enter press
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

// Start
connectWebSocket();
