// API Base URL
const API_BASE_URL =
    window.location.hostname === 'localhost'
        ? 'http://localhost:5000'
        : 'https://translator-api-0th4.onrender.com';

$(document).ready(function () {

    loadHistory();

    // Translate button
    $('#translate-btn').on('click', function () {
        translateText();
    });

    // Download history
    $('#download-history-btn').on('click', function () {
        window.open(API_BASE_URL + '/download_history_pdf', '_blank');
    });

    // --------------------------
    // TRANSLATE
    // --------------------------
    function translateText() {
        const text = $('#text-to-translate').val();
        const langFrom = $('#lang-from').val();
        const langTo = $('#lang-to').val();

        $.ajax({
            url: API_BASE_URL + '/translate',
            method: 'POST',
            data: {
                text: text,
                lang_from: langFrom,
                lang_to: langTo
            },
            xhrFields: { withCredentials: true },
            crossDomain: true,
            success: function (response) {
                if (response.translated_text) {
                    $('#translated-text').text(response.translated_text);
                    loadHistory();
                } else if (response.error) {
                    alert(response.error);
                }
            },
            error: function (err) {
                console.error(err);
                alert("Translation failed");
            }
        });
    }

    // --------------------------
    // LOAD HISTORY
    // --------------------------
    function loadHistory() {
        $.ajax({
            url: API_BASE_URL + '/history',
            method: 'GET',
            xhrFields: { withCredentials: true },
            crossDomain: true,
            success: function (data) {
                $('#history-list').empty();

                if (data.entries) {
                    data.entries.forEach(function (item) {
                        $('#history-list').append(
                            '<li>' +
                            item.source_text +
                            ' → ' +
                            item.translated_text +
                            '</li>'
                        );
                    });
                }
            },
            error: function (err) {
                console.error("History load failed", err);
            }
        });
    }

});
