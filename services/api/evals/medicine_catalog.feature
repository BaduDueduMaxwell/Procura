Feature: Buyers discover medicine availability from approved database evidence

  Scenario: A buyer searches a large quotation catalogue
    Given approved supplier quotations exist for 20 searchable medicines
    When the buyer searches the medicine catalogue
    Then Procura groups matching medicine variants by strength, dosage form, and pack size
    And it returns no more than twenty variants for the scrollable search panel
    And it reports quotation coverage, verified suppliers, capacity, delivery, currency, and destination evidence

  Scenario: A buyer starts a conversational request from a catalogue item
    Given the buyer selects a medicine variant
    When Procura prepares the request starter
    Then only the stored product facts are inserted
    And quantity, destination, deadline, and currency remain for the buyer to state

  Scenario: Internal roles cannot use the buyer catalogue
    Given a supplier or reviewer is signed in
    When that account requests the medicine catalogue
    Then access is denied

  Scenario: Equivalent strength formatting finds the same quotations
    Given an approved quotation stores a strength as 500 mg
    When a buyer requests the same product as 500mg or 500 MG
    Then Procura compares the request with that quotation
    And deterministic eligibility does not depend on whitespace or capitalization

  Scenario: A close medicine spelling is confirmed before evaluation
    Given a buyer asks for ameprazole and the catalog contains omeprazole
    When Procura checks the medicine name
    Then it asks whether the buyer meant omeprazole
    And it does not silently change the medicine or create a review case
    When the buyer confirms the suggestion
    Then Procura continues the same request with the canonical catalog medicine
