Feature: Role-specific Procura access

  Scenario: A seeded buyer can start procurement work without staff access
    Given a seeded buyer account
    When the buyer signs in
    Then the procurement dashboard and workspace are available
    And review, supplier, and operations routes are denied

  Scenario: A reviewer handles evidence without operational administration
    Given a seeded reviewer account
    When the reviewer signs in
    Then request reviews and supplier approvals are available
    And operations metrics and procurement creation are denied

  Scenario: An operations administrator can oversee the complete internal workflow
    Given a seeded administrator account
    When the administrator signs in
    Then procurement, request review, supplier approval, and operations routes are available
    And the administrator cannot impersonate a supplier portal account

  Scenario: An administrator inspects real operational inventory safely
    Given users, suppliers, quotations, medicines, and review work exist in the database
    When the administrator opens the control center
    Then real counts and searchable paginated account records are shown
    And password hashes and session records are never returned
    And a buyer, supplier, or reviewer cannot open those endpoints

  Scenario: Public users cannot grant themselves staff access
    Given the public signup form
    When a user requests a reviewer or administrator role
    Then the API rejects the request
