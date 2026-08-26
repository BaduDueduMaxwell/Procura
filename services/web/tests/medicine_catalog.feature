Feature: Buyers can discover supported medicines before making a request

  Scenario: Search current quotation coverage
    Given the buyer opens an empty procurement workspace
    When the medicine catalogue loads
    Then each medicine variant shows verified supplier coverage, capacity, delivery, market, currency, and price evidence

  Scenario: Use a medicine in a conversational request
    Given the buyer selects a catalogue medicine
    When the buyer chooses Use in request
    Then Procura fills only the product facts into the composer
    And the request is not sent until the buyer adds the remaining requirement and confirms it
