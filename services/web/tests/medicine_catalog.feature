Feature: Buyers can discover supported medicines before making a request

  Scenario: Search current quotation coverage without loading the full catalogue
    Given the buyer opens an empty procurement workspace with 20 searchable medicines
    When the buyer searches by medicine, strength, or dosage form
    Then the server returns no more than six matching variants
    And each result shows the supplier, quotation, and delivery evidence needed to choose it
    And the conversation remains vertically scrollable

  Scenario: Use a medicine in a conversational request
    Given the buyer selects a catalogue medicine
    When the buyer chooses Use in request
    Then Procura fills only the product facts into the composer
    And the request is not sent until the buyer adds the remaining requirement and confirms it
