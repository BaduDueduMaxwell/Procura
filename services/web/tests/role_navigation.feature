Feature: Role-aware navigation

  Scenario: A reviewer opens an administrator URL
    Given a signed-in reviewer
    When the reviewer opens the operations URL
    Then Procura redirects to request reviews
    And only request-review and supplier-approval navigation is shown

  Scenario: An administrator signs in
    Given a provisioned operations administrator
    When the administrator opens Procura
    Then operations is the default workspace
    And dashboard, procurement, review, supplier approval, and operations navigation is shown
