Feature: Connected procurement handoff
  The interpreted buyer request remains traceable while responsibility moves between roles.

  Scenario: Buyer opens a complete request to matching suppliers
    Given a buyer owns a complete interpreted procurement request
    When the buyer opens the request for supplier responses
    Then only suppliers with the matching medicine variant are invited
    And the original trace ID is retained
    And the action is recorded on the request timeline
    And no order is created

  Scenario: Invited supplier responds to one buyer request
    Given a supplier has an invitation for a buyer request
    When the supplier submits capacity, price, currency, and lead time
    Then the medicine, strength, dosage form, and pack size come from the buyer request
    And deterministic eligibility checks run on the response
    And one staff review case is created
    And an eligible recommendation produces an approval-oriented evidence brief
    And retrying the same idempotency key does not duplicate the response

  Scenario: Current evidence is required for approval
    Given a supplier response passed its original checks
    And the supplier authorization later expires
    When a reviewer attempts to approve the response
    Then approval remains blocked
    And the review case shows the refreshed authorization reason
    And the buyer receives a stored notification

  Scenario: Role boundaries protect request data
    Given two users do not own the same procurement request
    Then one buyer cannot read the other buyer's request
    And a supplier can only read requests sent to its linked profile
    And only a reviewer or administrator can decide the review case
