Feature: Buyers discover medicine availability from approved database evidence

  Scenario: A buyer browses current quotation coverage
    Given approved supplier quotations exist in the database
    When the buyer opens the medicine catalogue
    Then Procura groups matching medicine variants by strength, dosage form, and pack size
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
