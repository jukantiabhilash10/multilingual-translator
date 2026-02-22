$(document).ready(function() {
    // --- CSRF Token Setup ---
    let csrfToken = '';
    
    // Try to get CSRF token from meta tag or generate a new session
    function initCSRFToken() {
        // Make an initial request to get the CSRF token
        $.ajax({
            url: '/get_csrf_token',
            method: 'GET',
            success: function(response) {
                csrfToken = response.csrf_token;
                $('meta[name="csrf-token"]').attr('content', csrfToken);
            },
            error: function() {
                console.warn('Could not retrieve CSRF token');
            }
        });
    }
    
    function getCSRFToken() {
        return csrfToken || $('meta[name="csrf-token"]').attr('content') || '';
    }

    // Initialize CSRF token on page load
    initCSRFToken();

    // --- Setup AJAX to include CSRF token in all requests ---
    $.ajaxSetup({
        beforeSend: function(xhr, settings) {
            if (!(/^http:/.test(settings.url) || /^https:/.test(settings.url))) {
                // Only add CSRF token for relative URLs
                const token = getCSRFToken();
                if (token) {
                    xhr.setRequestHeader("X-CSRFToken", token);
                }
            }
        }
    });

    // --- Splash Screen & Main Container ---
    $('#getStartedBtn').on('click', function() {
        $('#splashScreen').fadeOut(400, function() {
            $('#main-flex-container').fadeIn(400);
        });
    });

    // --- Sidebar ---
    const sidebar = $('#sidebar-history');
    const translatorApp = $('#translatorApp');
    const toggleSidebarBtn = $('#toggleSidebarBtn');
    const toggleSidebarIcon = $('#toggleSidebarIcon');
    let sidebarVisible = localStorage.getItem('sidebarVisible') === 'true';

    function setSidebarVisible(visible) {
        if (visible) {
            sidebar.show();
            toggleSidebarIcon.text('«');
            translatorApp.removeClass('sidebar-closed');
        } else {
            sidebar.hide();
            toggleSidebarIcon.text('»');
            translatorApp.addClass('sidebar-closed');
        }
        // keep the outer state variable in sync so next toggle works
        sidebarVisible = !!visible;
        localStorage.setItem('sidebarVisible', sidebarVisible.toString());
    }

    setSidebarVisible(sidebarVisible);
    toggleSidebarBtn.on('click', () => setSidebarVisible(!sidebarVisible));

    // --- Translation ---
    $('#translateBtn').on('click', function() {
        const text = $('#inputText').val();
        const langFrom = $('#langFrom').val();
        const langTo = $('#langTo').val();
        const enableTransliteration = $('#transliterateCheckbox').is(':checked');
        const $btn = $(this);

        if (!text.trim()) {
            showError('Please enter text to translate.');
            return;
        }

        // Show loading state
        $btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm me-2" style="width:16px; height:16px;"></span>Translating...');

        $.ajax({
            url: '/translate',
            method: 'POST',
            data: {
                text: text,
                lang_from: langFrom,
                lang_to: langTo,
                transliterate: enableTransliteration
            },
            success: function(response) {
                if (response.translated_text) {
                    $('#outputText').val(response.translated_text);
                    fetchHistory();
                    updateTokenDisplay();
                    // Show token warning if present
                    if (response.warning) {
                        showWarning(response.warning);
                    }
                } else {
                    showError(response.error || 'An unknown error occurred.');
                }
            },
            error: function(xhr) {
                // Check if it's a token limit error
                if (xhr.status === 429) {
                    try {
                        const response = JSON.parse(xhr.responseText);
                        showError('⚠️ ' + (response.message || 'Token limit exceeded.'));
                        updateTokenDisplay();
                    } catch (e) {
                        showError('Token limit exceeded. Please register for more translations or try again tomorrow.');
                    }
                } else {
                    showError('An error occurred while communicating with the server.');
                }
            },
            complete: function() {
                $btn.prop('disabled', false).html('Translate');
            }
        });
    });

    // --- Transliteration ---
    $('#transliterateBtn').on('click', function() {
        const text = $('#inputText').val();
        const langTo = $('#langTo').val(); // Transliterate to the target language
        const $btn = $(this);

        if (!text.trim()) {
            showError('Please enter text to transliterate.');
            return;
        }

        $btn.prop('disabled', true).text('Transliterating...');

        $.ajax({
            url: '/transliterate',
            method: 'POST',
            data: {
                text: text,
                lang_to: langTo
            },
            success: function(response) {
                if (response.transliterated_text) {
                    $('#inputText').val(response.transliterated_text);
                    updateTokenDisplay();
                } else {
                    showError(response.error || 'An unknown error occurred.');
                }
            },
            error: function() {
                showError('An error occurred while communicating with the server.');
                updateTokenDisplay();
            },
            complete: function() {
                $btn.prop('disabled', false).text('Transliterate');
            }
        });
    });

    // --- History ---
    function fetchHistory() {
        $.get('/history', function(data) {
            const historyList = $('#translation-history-list');
            historyList.empty();
            
            // Handle paginated response format
            const entries = data.entries || (Array.isArray(data) ? data : []);
            
            if (entries && entries.length > 0) {
                entries.forEach(function(item) {
                    const listItem = `
                        <li class="list-group-item">
                            <span style="font-weight:600; color:#6366f1;">${item.source_lang_name || item.source_lang.toUpperCase()}</span> →
                            <span style="font-weight:600; color:#f472b6;">${item.target_lang_name || item.target_lang.toUpperCase()}</span><br>
                            <span style="color:#3730a3;">${item.source_text}</span> →
                            <span style="color:#27ae60;">${item.translated_text}</span><br>
                            <span style="font-size:0.85em; color:#888;">${new Date(item.timestamp).toLocaleString()}</span>
                        </li>`;
                    historyList.append(listItem);
                });
            } else {
                historyList.append('<li class="list-group-item">No translation history found.</li>');
            }
        }).fail(function() {
            const historyList = $('#translation-history-list');
            historyList.empty();
            historyList.append('<li class="list-group-item">Failed to load history.</li>');
        });
    }

    // --- Dark Mode ---
    const darkModeToggle = $('#darkModeToggle');
    const darkModeIcon = $('#darkModeIcon');
    let darkMode = localStorage.getItem('darkMode') === 'true';

    function setDarkMode(enabled) {
        $('body').toggleClass('dark-mode', enabled);
        darkModeIcon.text(enabled ? '☀️' : '🌙');
        localStorage.setItem('darkMode', enabled.toString());
    }

    setDarkMode(darkMode);
    darkModeToggle.on('click', () => setDarkMode(!$('body').hasClass('dark-mode')));

    // --- Utility Functions ---
    $('#clearAllBtn').on('click', function() {
        $('#inputText, #outputText').val('');
    });

    function showError(message) {
        // Simple alert for now, can be styled later
        alert(message);
    }
    
    function showWarning(message) {
        // Show warning in a non-blocking way
        console.warn(message);
        // Optionally show as toast or notification
        const div = $('<div>')
            .css({
                position: 'fixed',
                top: '80px',
                right: '24px',
                background: '#fff3cd',
                color: '#856404',
                padding: '12px 16px',
                borderRadius: '6px',
                border: '1px solid #ffc107',
                zIndex: 9999,
                maxWidth: '300px',
                fontSize: '0.9rem',
                fontWeight: '600'
            })
            .text(message);
        $('body').append(div);
        setTimeout(() => div.fadeOut(300, function() { $(this).remove(); }), 4000);
    }
    
    // --- Import / Download Handlers ---
    // Click import button -> open hidden file input
    $('#importFileBtn').on('click', function(e) {
        e.preventDefault();
        $('#fileInput').click();
    });

    // When a file is selected, POST it to the appropriate endpoint
    $('#fileInput').on('change', function() {
        const file = this.files[0];
        if (!file) return;
        const fd = new FormData();
        fd.append('file', file);

        const ext = (file.name || '').split('.').pop().toLowerCase();
        const url = ext === 'pdf' ? '/import_pdf' : '/import_txt';

        // Disable import button while uploading
        const $btn = $('#importFileBtn');
        $btn.prop('disabled', true).text('Importing...');

        $.ajax({
            url: url,
            method: 'POST',
            data: fd,
            processData: false,
            contentType: false,
            success: function(resp) {
                if (resp && resp.content) {
                    $('#inputText').val(resp.content);
                } else {
                    showError(resp && resp.error ? resp.error : 'Failed to import file.');
                }
            },
            error: function(xhr) {
                let msg = 'File import failed.';
                try { msg = xhr.responseJSON && xhr.responseJSON.error ? xhr.responseJSON.error : msg; } catch(e) {}
                showError(msg);
            },
            complete: function() {
                $btn.prop('disabled', false).text('Import');
                // clear file input so same file can be re-selected later
                $('#fileInput').val('');
            }
        });
    });

    // Download translated text as a plain .txt file (client-side)
    $('#downloadTextBtn').on('click', function(e) {
        e.preventDefault();
        const translated = $('#outputText').val();
        if (!translated || !translated.trim()) {
            showError('No translated text to download.');
            return;
        }

        const blob = new Blob([translated], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'translated_text.txt';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    });

    // Download translated PDF (server endpoint expected to return PDF blob)
    $('#downloadPdfBtn').on('click', function(e) {
        e.preventDefault();
        const text = $('#inputText').val() || '';
        const translated = $('#outputText').val() || '';
        const source_lang = $('#langFrom').val() || '';
        const target_lang = $('#langTo').val() || '';

        const fd = new FormData();
        fd.append('text', text);
        fd.append('translated_text', translated);
        fd.append('source_lang', source_lang);
        fd.append('target_lang', target_lang);

        const $btn = $(this);
        $btn.prop('disabled', true).text('Preparing PDF...');

        $.ajax({
            url: '/download_translated_pdf',
            method: 'POST',
            data: fd,
            processData: false,
            contentType: false,
            xhrFields: { responseType: 'blob' },
            success: function(data, status, xhr) {
                // Create a blob from the returned data and trigger download
                const contentType = xhr.getResponseHeader('Content-Type') || 'application/pdf';
                const blob = new Blob([data], { type: contentType });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'translated_text.pdf';
                document.body.appendChild(a);
                a.click();
                a.remove();
                URL.revokeObjectURL(url);
            },
            error: function(xhr) {
                let msg = 'Failed to download PDF.';
                try { msg = xhr.responseJSON && xhr.responseJSON.error ? xhr.responseJSON.error : msg; } catch(e) {}
                showError(msg);
            },
            complete: function() {
                $btn.prop('disabled', false).text('Download as PDF');
            }
        });
    });

    // Download translation history PDF (server endpoint expected to return PDF blob)
    $('#downloadHistoryPdfBtn').on('click', function(e) {
        e.preventDefault();
        const $btn = $(this);
        $btn.prop('disabled', true).text('Preparing...');

        $.ajax({
            url: '/download_history_pdf',
            method: 'GET',
            xhrFields: { responseType: 'blob' },
            success: function(data, status, xhr) {
                const contentType = xhr.getResponseHeader('Content-Type') || 'application/pdf';
                const blob = new Blob([data], { type: contentType });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'translation_history.pdf';
                document.body.appendChild(a);
                a.click();
                a.remove();
                URL.revokeObjectURL(url);
            },
            error: function(xhr) {
                showError('Failed to download history PDF.');
            },
            complete: function() {
                $btn.prop('disabled', false).text('Download History PDF');
            }
        });
    });

    // --- Voice Input & Speak (Text-to-Speech) ---
    // Minimal language name -> BCP47 code map for common languages; extend as needed
    const langCodeMap = {
        'Afrikaans': 'af',
        'Albanian': 'sq',
        'Amharic': 'am',
        'Arabic': 'ar',
        'Armenian': 'hy',
        'Azerbaijani': 'az',
        'Bengali': 'bn',
        'Bulgarian': 'bg',
        'Catalan': 'ca',
        'Chinese (simplified)': 'zh-CN',
        'Chinese (traditional)': 'zh-TW',
        'Croatian': 'hr',
        'Czech': 'cs',
        'Danish': 'da',
        'Dutch': 'nl',
        'English': 'en',
        'Estonian': 'et',
        'Filipino': 'fil',
        'Finnish': 'fi',
        'French': 'fr',
        'German': 'de',
        'Greek': 'el',
        'Gujarati': 'gu',
        'Hebrew': 'he',
        'Hindi': 'hi',
        'Hungarian': 'hu',
        'Indonesian': 'id',
        'Italian': 'it',
        'Japanese': 'ja',
        'Kannada': 'kn',
        'Korean': 'ko',
        'Malay': 'ms',
        'Malayalam': 'ml',
        'Marathi': 'mr',
        'Nepali': 'ne',
        'Polish': 'pl',
        'Portuguese': 'pt',
        'Punjabi': 'pa',
        'Romanian': 'ro',
        'Russian': 'ru',
        'Serbian': 'sr',
        'Sinhala': 'si',
        'Slovak': 'sk',
        'Spanish': 'es',
        'Swahili': 'sw',
        'Swedish': 'sv',
        'Tamil': 'ta',
        'Telugu': 'te',
        'Thai': 'th',
        'Turkish': 'tr',
        'Urdu': 'ur',
        'Vietnamese': 'vi',
        'Xhosa': 'xh',
        'Zulu': 'zu',
        'Auto-Detect': 'en'
    };

    let recognizing = false;
    let recognition = null;

    $('#voiceInputBtn').on('click', function() {
        // Check browser support
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            showError('Speech recognition is not supported in this browser. Use Chrome or Edge.');
            return;
        }

        // If already recognizing, stop
        if (recognizing && recognition) {
            recognition.stop();
            return;
        }

        // Create a new recognition instance
        recognition = new SpeechRecognition();
        const selectedLang = $('#langFrom').val();
        recognition.lang = langCodeMap[selectedLang] || 'en-US';
        recognition.interimResults = false;
        recognition.maxAlternatives = 1;

        recognition.onstart = function() {
            recognizing = true;
            $('#voiceInputBtn').text('Listening...');
        };

        recognition.onresult = function(event) {
            // Concatenate all results
            let transcript = '';
            for (let i = event.resultIndex; i < event.results.length; ++i) {
                transcript += event.results[i][0].transcript;
            }
            // Append to the input textarea (preserve existing text)
            const current = $('#inputText').val() || '';
            $('#inputText').val((current ? current + ' ' : '') + transcript);
        };

        recognition.onerror = function(evt) {
            console.error('Speech recognition error', evt);
            showError('Speech recognition error: ' + (evt.error || 'unknown'));
        };

        recognition.onend = function() {
            recognizing = false;
            $('#voiceInputBtn').text('Voice Input');
        };

        try {
            recognition.start();
        } catch (err) {
            console.error('Recognition start error', err);
            showError('Could not start speech recognition.');
        }
    });

    // Speak translated text (TTS)
    // Ensure voices are loaded
    let availableVoices = [];
    function loadVoices() {
        availableVoices = window.speechSynthesis ? window.speechSynthesis.getVoices() : [];
    }
    if (window.speechSynthesis) {
        loadVoices();
        window.speechSynthesis.onvoiceschanged = loadVoices;
    }

    $('#speakBtn').on('click', function() {
        const text = $('#outputText').val();
        if (!text || !text.trim()) {
            showError('No translated text to speak.');
            return;
        }

        const targetLang = $('#langTo').val();
        
        // Use server-side gTTS for better language support
        $.ajax({
            url: '/speak',
            type: 'POST',
            data: {
                text: text,
                lang_to: targetLang
            },
            xhrFields: {
                responseType: 'blob'
            },
            success: function(data) {
                // Create audio player and play the response
                const audioUrl = URL.createObjectURL(data);
                const audio = new Audio(audioUrl);
                
                $('#speakBtn').text('Stop');
                
                audio.onplay = function() {
                    $('#speakBtn').text('Stop');
                };
                
                audio.onended = function() {
                    $('#speakBtn').text('Speak Translated Text');
                    URL.revokeObjectURL(audioUrl);
                };
                
                audio.onerror = function() {
                    $('#speakBtn').text('Speak Translated Text');
                    showError('Error playing audio.');
                    URL.revokeObjectURL(audioUrl);
                };
                
                // If already playing, stop
                if (window.currentAudio && !window.currentAudio.paused) {
                    window.currentAudio.pause();
                    window.currentAudio.currentTime = 0;
                    $('#speakBtn').text('Speak Translated Text');
                    return;
                }
                
                window.currentAudio = audio;
                audio.play().catch(function(err) {
                    console.error('Audio play error:', err);
                    $('#speakBtn').text('Speak Translated Text');
                    showError('Failed to play audio: ' + err.message);
                });
            },
            error: function(xhr, status, error) {
                $('#speakBtn').text('Speak Translated Text');
                console.error('TTS error:', error);
                try {
                    const response = JSON.parse(xhr.responseText);
                    showError('Error: ' + (response.details || response.error || 'Unknown error'));
                } catch (e) {
                    showError('Error during speech synthesis: ' + error);
                }
            }
        });
    });

    // Initial Load
    fetchHistory();
    
    // --- Token Management ---
    function updateTokenDisplay() {
        $.ajax({
            url: '/token_status',
            method: 'GET',
            success: function(response) {
                const remaining = response.tokens_remaining;
                const limit = response.tokens_limit;
                const percentUsed = response.percent_used;
                
                $('#tokensRemaining').text(remaining);
                $('#tokensLimit').text(limit);
                
                // Update progress bar
                const progressPercent = (100 - percentUsed);
                $('#tokenProgressBar').css('width', progressPercent + '%');
                
                // Update username display and badge
                if (response.is_registered) {
                    $('#usernameDisplay').text(response.username || 'Registered User');
                    $('#registeredBadge').show();
                    $('#guestBadge').hide();
                } else {
                    $('#usernameDisplay').text('');
                    $('#guestBadge').show();
                    $('#registeredBadge').hide();
                }
                
                // Add tooltip for more info
                const status = `${limit - remaining}/${limit} tokens used today`;
                $('#tokenDisplay').attr('title', status);
            },
            error: function() {
                console.error('Failed to fetch token status');
            }
        });
    }
    
    // Update tokens every 5 seconds and when page loads
    updateTokenDisplay();
    setInterval(updateTokenDisplay, 5000);

    // --- Swap Languages Button ---
    $('#swapLangBtn').on('click', function() {
        // Swap the selected languages
        const langFromSelect = $('#langFrom');
        const langToSelect = $('#langTo');
        const tempLang = langFromSelect.val();
        langFromSelect.val(langToSelect.val());
        langToSelect.val(tempLang);

        // Swap the input and output text areas
        const inputText = $('#inputText').val();
        const outputText = $('#outputText').val();
        $('#inputText').val(outputText);
        $('#outputText').val(inputText);
    });
});
