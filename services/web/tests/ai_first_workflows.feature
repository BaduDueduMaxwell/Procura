Feature: Role workflows begin with guided assistance

  Scenario: A buyer resolves a duplicate without leaving Procura
    Given an uploaded procurement list contains the same requirement twice
    When the buyer reviews the duplicate finding
    Then the buyer can remove that row or confirm both requirements are intentional
    And a removed row remains restorable before submission
    And the original row count and buyer action remain auditable

  Scenario: Human-review copy names the failed safeguard
    Given a procurement workflow cannot complete a required check
    Then the buyer sees the specific failed safeguard in plain language
    And the interface never shows a programming exception name

  Scenario: Supplier opens quotation details without changing them
    Given the supplier dashboard shows active quotations
    When the supplier selects the active quotation count and opens a quotation
    Then its capacity, lead time, price, and identifier are visible
    And no withdrawal request is created until the supplier selects that separate action

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
