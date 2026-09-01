Feature: Role-aware navigation

  Scenario: A buyer reopens a recent procurement decision
    Given the buyer dashboard lists a persisted decision
    And the decision is identified by medicine and strength
    When the buyer opens that decision
    Then Procura navigates to a stable decision URL
    And restores the original conversation and decision evidence

  Scenario: Operational records open instead of acting like static rows
    Given a reviewer, supplier, or operations user sees a record list
    And medicine-related records are identified by medicine and strength
    When the user selects a case, quotation, submission, or trace
    Then Procura opens the corresponding evidence on a stable role-appropriate URL
    And the interaction is available by keyboard

  Scenario: Collapsed navigation remains understandable
    Given the navigation is collapsed at a tablet width
    When a buyer moves through the navigation with a keyboard or screen reader
    Then Dashboard and Workspace retain their accessible names

  Scenario: A reviewer opens an administrator URL
    Given a signed-in reviewer
    When the reviewer opens the operations URL
    Then Procura redirects to request reviews
    And only request-review and supplier-approval navigation is shown

  Scenario: An administrator signs in
    Given a provisioned operations administrator
    When the administrator opens Procura
    Then operations is the default workspace
    And dashboard, procurement, review, supplier approval, operations, and administration navigation is shown

  Scenario: An administrator searches the control center
    Given a provisioned operations administrator
    When the administrator filters users by name, organization, role, or status
    Then matching database accounts are shown with role and access state
    When the administrator searches medicine coverage
    Then matching variants show quotations, verified suppliers, capacity, and markets
    And the control center does not expose account credentials or sessions
