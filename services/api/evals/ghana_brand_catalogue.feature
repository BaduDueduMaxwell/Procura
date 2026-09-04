Feature: Ghana medicine brands return to the buyer for confirmation

  Scenario: A registered Kinapharma brand is recognized
    Given a buyer enters Locid 20 mg capsules
    When Procura checks the versioned Ghana FDA reference catalogue
    Then it suggests omeprazole
    And it shows the source record and manufacturer
    And it preserves Locid as the original value
    And it does not create a staff-review case

  Scenario Outline: Brands from different manufacturers are supported
    Given a buyer enters <brand>
    When Procura checks the Ghana brand catalogue
    Then it suggests <generic>
    And requires the buyer to accept or reject the mapping

    Examples:
      | brand       | generic                   |
      | Coartem     | artemether-lumefantrine   |
      | Glucophage  | metformin                 |
      | Ciprobay    | ciprofloxacin             |
      | Dialet      | glibenclamide             |

  Scenario: An unverified brand is not invented
    Given a buyer enters Kinaprazole
    And no active Ghana FDA source record exists in the curated catalogue
    When Procura validates the medicine
    Then it does not claim Kinaprazole maps to omeprazole
    And it asks the buyer to correct or identify the medicine

  Scenario: The intake template stays focused
    When a buyer downloads the CSV template
    Then it includes the required quantity units column
    And it does not include a buyer notes column
