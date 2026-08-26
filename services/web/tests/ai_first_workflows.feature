Feature: Role workflows begin with guided assistance

  Scenario: A supplier prepares a quotation from one description
    Given the supplier describes the complete commercial offer
    When the supplier asks Procura to prepare a draft
    Then the quotation form is filled with the extracted facts
    And the supplier must still press the separate submission button

  Scenario: A reviewer sees a suggested action with its evidence
    Given a procurement case is open for review
    When the reviewer opens the case
    Then Procura displays an evidence brief and a suggested action
    And no review action is recorded until the reviewer chooses a decision button
