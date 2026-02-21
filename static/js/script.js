// This file contains client-side JavaScript code that handles user interactions, AJAX requests to the server for translation and transliteration, and manages local storage for user preferences.

// API Base URL - configure for your backend deployment
const API_BASE_URL = window.location.hostname === 'localhost' ? 'http://localhost:5000' : 'https://translator-api-0th4.onrender.com';

$(document).ready(function() {
    // Load available languages and translation history on page load
    loadLanguages();
    loadHistory();

    // Event handler for translation form submission
    $('#translate-form').on('submit', function(event) {
        event.preventDefault();
        translateText();
    });

    // Event handler for transliteration checkbox
    $('#transliterate-checkbox').on('change', function() {
        toggleTransliterate();
    });

    // Event handler for importing files
    $('#import-file').on('change', function(event) {
        importFile(event.target.files[0]);
    });

    // Event handler for downloading translated PDF
    $('#download-pdf').on('click', function() {
        downloadTranslatedPDF();
    });

    // Event handler for downloading history PDF
    $('#download-history').on('click', function() {
        downloadHistoryPDF();
    });

    // Function to load available languages
    function loadLanguages() {
        $.get(API_BASE_URL + '/languages', function(data) {
            // Populate language selection dropdowns
            // Assuming data is an array of language objects
            data.forEach(function(lang) {
                $('#lang-from').append(new Option(lang.name, lang.code));
                $('#lang-to').append(new Option(lang.name, lang.code));
            });
        });
    }

    // Function to load translation history
    function loadHistory() {
        $.get(API_BASE_URL + '/history', function(data) {
            // Populate history display
            data.forEach(function(item) {
                $('#history').append('<li>' + item.text + ' -> ' + item.translated_text + '</li>');
            });
        });
    }

    // Function to translate text
    function translateText() {
        const text = $('#text-input').val();
        const langFrom = $('#lang-from').val();
        const langTo = $('#lang-to').val();
        const transliterate = $('#transliterate-checkbox').is(':checked');

        $.post(API_BASE_URL + '/translate', { text, lang_from: langFrom, lang_to: langTo, transliterate }, function(response) {
            $('#translated-output').text(response.translated_text);
            saveToHistory(text, response.translated_text);
        });
    }

    // Function to toggle transliteration
    function toggleTransliterate() {
        // Logic to handle transliteration checkbox state
    }

    // Function to import a file
    function importFile(file) {
        const formData = new FormData();
        formData.append('file', file);

        $.ajax({
            url: API_BASE_URL + '/import_txt',
            type: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            success: function(response) {
                $('#text-input').val(response.text);
            }
        });
    }

    // Function to download translated PDF
    function downloadTranslatedPDF() {
        const text = $('#text-input').val();
        const translatedText = $('#translated-output').text();
        const sourceLang = $('#lang-from').val();
        const targetLang = $('#lang-to').val();

        $.post(API_BASE_URL + '/download_translated_pdf', { text, translated_text: translatedText, source_lang: sourceLang, target_lang: targetLang }, function(blob) {
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'translated.pdf';
            document.body.append(a);
            a.click();
            a.remove();
        });
    }

    // Function to download history PDF
    function downloadHistoryPDF() {
        window.location.href = '/download_history_pdf';
    }

    // Function to save translation to history
    function saveToHistory(originalText, translatedText) {
        // Logic to save translation history
    }
});