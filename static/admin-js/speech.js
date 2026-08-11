document.addEventListener('DOMContentLoaded', function() {
    const recordBtn = document.getElementById('recordBtn');
    const translateBtn = document.getElementById('translateBtn');
    const listenBtn = document.getElementById('listenBtn');
    const saveBtn = document.getElementById('saveBtn');
    
    let recognition;
    let recordedText = '';
    
    // Initialize speech recognition
    if ('webkitSpeechRecognition' in window) {
        recognition = new webkitSpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = true;
        
        recognition.onresult = function(event) {
            let interimTranscript = '';
            let finalTranscript = '';
            
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const transcript = event.results[i][0].transcript;
                if (event.results[i].isFinal) {
                    finalTranscript += transcript;
                } else {
                    interimTranscript += transcript;
                }
            }
            
            document.getElementById('originalText').innerHTML = finalTranscript + interimTranscript;
            recordedText = finalTranscript;
        };
    }
    
    // Button handlers
    recordBtn.addEventListener('click', function() {
        if (recordBtn.textContent.includes('Start')) {
            recognition.start();
            recordBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Recording';
        } else {
            recognition.stop();
            recordBtn.innerHTML = '<i class="fas fa-microphone"></i> Start Recording';
        }
    });
    
    translateBtn.addEventListener('click', function() {
        if (!recordedText) {
            alert('Please record some audio first');
            return;
        }
        
        fetch('/translate/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify({
                text: recordedText,
                target_lang: 'en'
            })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(data => {
            if (data.error) {
                console.error('Translation error:', data.error);
                alert('Translation failed: ' + data.error);
            } else {
                document.getElementById('translatedText').textContent = data.translated_text;
            }
        })
        .catch(error => {
            console.error('Translation error:', error);
            alert('Translation failed: ' + error.message);
        });
    });
    
    // Complete getCookie function
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    
});