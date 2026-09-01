Feature: Role handoff interface
  Scenario: Buyer sends a request to the supplier portal
    Given the request interpreter has produced a complete request
    When the buyer selects "Open to matching suppliers"
    Then the interface shows how many matching suppliers can respond
    And states that no order was placed

  Scenario: Supplier responds without retyping the medicine
    Given an invited request appears in the supplier portal
    When the supplier opens it
    Then the medicine requirement is visible and locked to the buyer's request
    And the supplier enters only capacity, unit price, currency, and lead time

  Scenario: Every role receives durable updates
    Given a lifecycle action affects the signed-in account
    Then an unread count appears in Notifications
    And opening the notification marks it read
    And the request timeline keeps the dated event after a page reload
