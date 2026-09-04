Feature: AI-first role assistance preserves human control

  Scenario: Buyer dashboard counts submitted requests rather than empty workspaces
    Given a buyer opens the procurement workspace several times without submitting a request
    Then Requests opened remains zero
    When the buyer submits one request and answers its clarification
    Then the dashboard shows one opened request and one latest request state

  Scenario: Safe failures explain the review reason without developer terminology
    Given a required verification step fails
    When Procura creates a human-review case
    Then the buyer and reviewer see the failed check in plain language
    And neither screen exposes Python exception class names

  Scenario: Supplier quotation evidence is inspectable
    Given a supplier has active quotations
    When the supplier opens the active quotation summary or a quotation row
    Then Procura shows capacity, delivery, price, and the quotation identifier
    And withdrawal remains a separate staff-verified action

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

  Scenario: Repeated supplier failures are summarized for review
    Given every quotation misses the requested delivery window
    And some quotations also have expired authorization or an unverified currency conversion
    When Procura prepares the reviewer evidence
    Then the delivery failures are grouped into one sentence with every observed lead time
    And authorization, currency, and final eligibility are shown as separate evidence categories
    And supplier-level details remain available on the quotation rows
