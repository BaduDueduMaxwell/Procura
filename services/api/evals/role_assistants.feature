Feature: AI-first role assistance preserves human control

  Scenario: A supplier turns a natural-language offer into a quotation draft
    Given a supplier describes medicine, units, availability, price, currency, and lead time
    When Procura prepares the quotation draft
    Then every stated field is extracted into the typed quotation form
    And no supplier submission is created until the supplier confirms it

  Scenario: An incomplete supplier offer remains incomplete
    Given a supplier description omits price and delivery timing
    When Procura prepares the quotation draft
    Then the missing fields are named
    And the draft is not marked ready to submit

  Scenario: A reviewer receives a non-binding evidence brief
    Given a procurement case requires human review
    When Procura prepares the review brief
    Then the brief cites the stored escalation and quotation evidence
    And it suggests an action without changing the case status
