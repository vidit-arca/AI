document.addEventListener('DOMContentLoaded', () => {
    const chatForm = document.getElementById('chatForm');
    const userInput = document.getElementById('userInput');
    const chatContainer = document.getElementById('chatContainer');
    const sendBtn = document.getElementById('sendBtn');

    // Auto-resize textarea
    userInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        if (this.value === '') {
            this.style.height = '56px';
        }
    });

    // Handle Enter to submit, Shift+Enter for new line
    userInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (userInput.value.trim() !== '') {
                chatForm.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
            }
        }
    });

    // --- Voice Assistance Logic ---
    const micBtn = document.getElementById('micBtn');
    let recognition = null;
    let isListening = false;
    let originalText = ''; // Store text before listening starts

    // Check for browser support
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
        recognition = new SpeechRecognition();
        recognition.continuous = true; // Allow continuous listening until user stops
        recognition.interimResults = true;
        recognition.lang = 'en-US';

        recognition.onstart = () => {
            isListening = true;
            micBtn.classList.add('listening');
            userInput.placeholder = "Listening...";
            originalText = userInput.value;
            if (originalText.length > 0 && !originalText.endsWith(' ')) {
                originalText += ' ';
            }
        };

        recognition.onresult = (event) => {
            let interimTranscript = '';
            let finalTranscript = '';

            for (let i = event.resultIndex; i < event.results.length; ++i) {
                if (event.results[i].isFinal) {
                    finalTranscript += event.results[i][0].transcript;
                } else {
                    interimTranscript += event.results[i][0].transcript;
                }
            }

            if (finalTranscript !== '') {
                originalText += finalTranscript + ' ';
                userInput.value = originalText;
            } else {
                userInput.value = originalText + interimTranscript;
            }
            userInput.dispatchEvent(new Event('input')); // auto-resize trigger
        };

        recognition.onerror = (event) => {
            console.error("Speech recognition error:", event.error, event);
            isListening = false;
            micBtn.classList.remove('listening');
            
            let errorMessage = "Error accessing microphone.";
            if (event.error === 'not-allowed') {
                errorMessage = "Mic access denied (Ensure you are on HTTPS or localhost).";
            }
            userInput.placeholder = errorMessage;
            
            setTimeout(() => {
                userInput.placeholder = "Ask the agent to create a task...";
            }, 5000);
        };

        recognition.onend = () => {
            // If the user hasn't manually stopped it, but it ended (e.g. timeout), restart or reset
            isListening = false;
            micBtn.classList.remove('listening');
            userInput.placeholder = "Ask the agent to create a task...";
        };

        micBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            if (isListening) {
                recognition.stop();
            } else {
                try {
                    // Diagnostic step: Forcefully request standard microphone access first
                    try {
                        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                        stream.getTracks().forEach(track => track.stop());
                        console.log("Diagnostic: getUserMedia succeeded! Permission is granted.");
                    } catch (permErr) {
                        console.error("Diagnostic failed:", permErr);
                        alert("Chrome is actively blocking microphone access for this site.\n\nError: " + permErr.name + "\n\nPlease click the Lock/Settings icon next to the URL, change Microphone to 'Allow', and refresh the page.");
                        userInput.placeholder = "Microphone blocked by Chrome settings.";
                        return;
                    }

                    // Start speech recognition directly after diagnostic
                    recognition.start();
                } catch (err) {
                    console.error("Recognition start error:", err);
                    alert("SpeechRecognition API failed to start: " + err.message);
                }
            }
        });
    } else {
        micBtn.style.display = 'none'; // Hide if not supported
        console.warn("Speech Recognition API not supported in this browser. Please use Chrome, Edge, or Safari.");
    }
    // -----------------------------

    function appendMessage(sender, htmlContent) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${sender}-message`;
        
        const avatar = document.createElement('div');
        avatar.className = 'avatar';
        avatar.textContent = sender === 'user' ? 'U' : 'AI';
        
        const bubble = document.createElement('div');
        bubble.className = 'bubble';
        bubble.innerHTML = htmlContent;
        
        if (sender === 'user') {
            messageDiv.appendChild(bubble);
            messageDiv.appendChild(avatar);
        } else {
            messageDiv.appendChild(avatar);
            messageDiv.appendChild(bubble);
        }
        
        chatContainer.appendChild(messageDiv);
        chatContainer.scrollTop = chatContainer.scrollHeight;
        return bubble; // return bubble for further manipulation
    }

    function showTypingIndicator() {
        const indicator = document.createElement('div');
        indicator.className = 'message ai-message typing-indicator-container';
        indicator.innerHTML = `
            <div class="avatar">AI</div>
            <div class="bubble typing-indicator">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        `;
        chatContainer.appendChild(indicator);
        chatContainer.scrollTop = chatContainer.scrollHeight;
        return indicator;
    }

    function setInputEnabled(enabled) {
        userInput.disabled = !enabled;
        sendBtn.disabled = !enabled;
        if (enabled) userInput.focus();
    }

    async function renderResponse(data) {
        // Handle pending delete confirmation flow
        if (data.status === 'pending_delete') {
            const taskIds = data.tasks.map(t => t.id);
            
            // Build confirmation bubble HTML
            let html = '⚠️ <strong>Please confirm deletion of these tasks:</strong><br><br>';
            data.tasks.forEach(t => {
                html += `🗑️ <a href="${t.url}" target="_blank" rel="noopener noreferrer">#${t.id}: ${t.subject}</a><br>`;
            });
            html += `<br><div class="confirm-buttons">
                <button class="confirm-btn danger" id="confirmDeleteBtn">🗑️ Confirm Delete (${taskIds.length})</button>
                <button class="confirm-btn cancel" id="cancelDeleteBtn">✕ Cancel</button>
            </div>`;
            
            const bubble = appendMessage('ai', html);
            
            // Wire up the confirmation buttons
            bubble.querySelector('#confirmDeleteBtn').addEventListener('click', async () => {
                bubble.querySelector('.confirm-buttons').innerHTML = '<em>Deleting...</em>';
                setInputEnabled(false);
                try {
                    const resp = await fetch('/api/confirm-delete', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ task_ids: taskIds })
                    });
                    const result = await resp.json();
                    bubble.querySelector('.confirm-buttons').remove();
                    
                    let resultHtml = '<strong>Deletion Results:</strong><br><br>';
                    if (result.tasks && result.tasks.length > 0) {
                        result.tasks.forEach(t => {
                            resultHtml += `✅ Deleted: #${t.id}<br>`;
                        });
                    }
                    if (result.failed && result.failed.length > 0) {
                        result.failed.forEach(f => {
                            resultHtml += `❌ ${f.subject}: ${f.error}<br>`;
                        });
                    }
                    bubble.innerHTML += resultHtml;
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                } catch (err) {
                    bubble.querySelector('.confirm-buttons').innerHTML = '<strong style="color:#f87171">Network error during deletion.</strong>';
                } finally {
                    setInputEnabled(true);
                }
            });
            
            bubble.querySelector('#cancelDeleteBtn').addEventListener('click', () => {
                bubble.querySelector('.confirm-buttons').innerHTML = '<em style="color:#9ca3af">Deletion cancelled.</em>';
                chatContainer.scrollTop = chatContainer.scrollHeight;
            });
            return;
        }

        // Handle pending create confirmation flow
        if (data.status === 'pending_create') {
            const payloads = data.tasks.map(t => t.payload);
            
            // Build confirmation bubble HTML
            let html = '⚠️ <strong>Please confirm creation of these tasks:</strong><br><br>';
            data.tasks.forEach(t => {
                html += `<strong>Subject:</strong> ${t.subject}<br>`;
                if (t.description) html += `<strong>Description:</strong> ${t.description}<br>`;
                html += `<strong>Project ID:</strong> ${t.project_id}<br>`;
                if (t.version_str) html += `<strong>Version:</strong> ${t.version_str}<br>`;
                if (t.parent_title) html += `<strong>Parent Task:</strong> ${t.parent_title}<br>`;
                html += `<hr>`;
            });
            html += `<div class="confirm-buttons">
                <button class="confirm-btn" style="background-color: #10b981;" id="confirmCreateBtn">✅ Confirm Create (${payloads.length})</button>
                <button class="confirm-btn cancel" id="cancelCreateBtn">✕ Cancel</button>
            </div>`;
            
            const bubble = appendMessage('ai', html);
            
            // Wire up the confirmation buttons
            bubble.querySelector('#confirmCreateBtn').addEventListener('click', async () => {
                bubble.querySelector('.confirm-buttons').innerHTML = '<em>Creating...</em>';
                setInputEnabled(false);
                try {
                    const resp = await fetch('/api/confirm-create', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ payloads: payloads })
                    });
                    const result = await resp.json();
                    bubble.querySelector('.confirm-buttons').remove();
                    
                    let resultHtml = '<strong>Creation Results:</strong><br><br>';
                    if (result.tasks && result.tasks.length > 0) {
                        result.tasks.forEach(t => {
                            resultHtml += `✅ Created: <a href="${t.url}" target="_blank" rel="noopener noreferrer">#${t.id}: ${t.subject}</a><br>`;
                        });
                    }
                    if (result.failed && result.failed.length > 0) {
                        result.failed.forEach(f => {
                            resultHtml += `❌ ${f.subject}: ${f.error}<br>`;
                        });
                    }
                    bubble.innerHTML += resultHtml;
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                } catch (err) {
                    bubble.querySelector('.confirm-buttons').innerHTML = '<strong style="color:#f87171">Network error during creation.</strong>';
                } finally {
                    setInputEnabled(true);
                }
            });
            
            bubble.querySelector('#cancelCreateBtn').addEventListener('click', () => {
                bubble.querySelector('.confirm-buttons').innerHTML = '<em style="color:#9ca3af">Creation cancelled.</em>';
                chatContainer.scrollTop = chatContainer.scrollHeight;
            });
            return;
        }

        // Normal success response
        let html = '';
        if (data.tasks && data.tasks.length > 0) {
            html += '<strong>Successfully Processed Tasks:</strong><br><br>';
            data.tasks.forEach(t => {
                let actionText = t.action === "delete" ? "Deleted" : t.action === "update" ? "Updated" : t.action === "find" ? "Found" : t.action === "search" ? "🔍 Found" : t.action === "comment" ? "💬 Commented on" : "Created";
                if (t.url) {
                    html += `👉 ${actionText}: <a href="${t.url}" target="_blank" rel="noopener noreferrer">#${t.id}: ${t.subject}</a><br>`;
                } else {
                    html += `👉 ${actionText}: #${t.id}: ${t.subject}<br>`;
                }
                
                if (t.details) {
                    html += `<ul style="margin-top: 5px; margin-bottom: 15px; font-size: 0.9em; color: #4b5563;">`;
                    if (t.details.project) html += `<li><strong>Project:</strong> ${t.details.project}</li>`;
                    if (t.details.status) html += `<li><strong>Status:</strong> ${t.details.status}</li>`;
                    if (t.details.version) html += `<li><strong>Version/Sprint:</strong> ${t.details.version}</li>`;
                    html += `</ul>`;
                }
            });
        }
        if (data.failed && data.failed.length > 0) {
            html += '<br><strong style="color: #f87171;">Failed to process:</strong><br>';
            data.failed.forEach(f => {
                html += `❌ <em>${f.subject}</em>: ${f.error}<br>`;
            });
        }
        if (!html) html = "No tasks were processed.";
        appendMessage('ai', html);
    }

    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const text = userInput.value.trim();
        if (!text) return;

        appendMessage('user', text);
        userInput.value = '';
        userInput.style.height = '56px';
        
        setInputEnabled(false);
        const typingIndicator = showTypingIndicator();

        try {
            const response = await fetch('/api/agent', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt: text })
            });

            const data = await response.json();
            typingIndicator.remove();
            
            if (response.ok) {
                await renderResponse(data);
            } else {
                appendMessage('ai', `<strong>Error:</strong> ${data.detail || 'Something went wrong.'}`);
            }
        } catch (error) {
            typingIndicator.remove();
            appendMessage('ai', `<strong>Network Error:</strong> Cannot reach the server.`);
        } finally {
            setInputEnabled(true);
        }
    });
});
