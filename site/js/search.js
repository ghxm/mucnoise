document.addEventListener('DOMContentLoaded', function() {

    var inputGroup = document.createElement('div');
    inputGroup.className = 'input-group';

    var searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.className = 'form-control';
    searchInput.placeholder = 'Filter...';
    searchInput.id = 'searchBar';

    var searchButton = document.createElement('button');
    searchButton.type = 'button';
    searchButton.className = 'btn btn-outline-primary btn-sm';

    var SearchIcon = document.createElement('i');
    SearchIcon.className = 'fa fa-search';
    searchButton.appendChild(SearchIcon);

    // add the search button to the menu
    var menu = document.getElementById('row-top').getElementsByTagName('div')[0];
    menu.appendChild(searchButton)


    var clearButton = document.createElement('button');
    clearButton.type = 'button';
    clearButton.className = 'btn bg-transparent';
    clearButton.style = 'margin-left: -40px; z-index: 100;';

    var clearIcon = document.createElement('i');
    clearIcon.className = 'fa fa-times';
    clearButton.appendChild(clearIcon);

    // Append the input and button to the input-group
    inputGroup.appendChild(searchInput);
    inputGroup.appendChild(clearButton);

    var searchPlaceholder = document.getElementById('search');
    searchPlaceholder.getElementsByTagName('div')[0].appendChild(inputGroup);

    // Insert the input group into the page
    // document.body.insertBefore(inputGroup, document.body.firstChild);
    // Function to filter the events and their corresponding info rows
    function filterEvents() {
        var input, filter, eventRows, eventRow, eventInfoRow, i, txtValue, combinedText;
        input = document.getElementById('searchBar');
        filter = input.value.toUpperCase();
        eventRows = document.getElementsByClassName('row-event'); // Class name for event row elements

        // Loop through all event rows and hide those that don't match the search query along with their info rows
        for (i = 0; i < eventRows.length; i++) {
            eventRow = eventRows[i];
            eventInfoRow = eventRow.nextElementSibling && eventRow.nextElementSibling.classList.contains('row-event-info') ? eventRow.nextElementSibling : null;
            // Combine the text content of the event row and the info row for searching
            combinedText = (eventRow.textContent || eventRow.innerText) + (eventInfoRow ? (eventInfoRow.textContent || eventInfoRow.innerText) : '');
            if (combinedText.toUpperCase().indexOf(filter) > -1) {
                eventRow.style.display = '';
                if (eventInfoRow) eventInfoRow.style.display = '';
            } else {
                eventRow.style.display = 'none';
                if (eventInfoRow) eventInfoRow.style.display = 'none';
            }
        }

        // Loop through all day or week containers and hide those that don't have any visible events
        var dayWeekContainers = document.querySelectorAll('[id^="date-"], [id^="kw-"]');
        for (i = 0; i < dayWeekContainers.length; i++) {
            var dayWeekContainer = dayWeekContainers[i];
            var visibleEvents = dayWeekContainer.querySelectorAll('.row-event:not([style*="display: none"])');
            console.log(dayWeekContainer.id)
            console.log(visibleEvents.length);
            dayWeekContainer.style.display = visibleEvents.length > 0 ? '' : 'none';
        }
    }

    // hide the search bar so that it doesnt take up space
    searchPlaceholder.classList.add('d-none');


    // Attach the filterEvents function to the search bar's input event
    searchInput.addEventListener('input', filterEvents);
    // Event listener for the clear button
    clearButton.addEventListener('click', function() {
        searchInput.value = ''; // Clears the content of the search bar
        filterEvents(); // Calls the filterEvents function to update the display of the page elements
    });

    // Event listener for the search button
    searchButton.addEventListener('click', function() {
        searchButton.classList.remove('active');
        // show / hide the search bar
        if (searchPlaceholder.classList.contains('d-none')) {
            searchPlaceholder.classList.remove('d-none');
            searchInput.focus();
            // make the button look pressed
            searchButton.classList.add('active');
        } else {
            searchPlaceholder.classList.add('d-none');
            searchInput.value = '';
            filterEvents();
            // release the button
        }
    });

});
