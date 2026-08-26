Feature: Hosted Gemini interpretation stays inside Procura's autonomy boundary

  Scenario: Gemini converts buyer language into a typed request
    Given a buyer describes a medicine requirement in natural language
    When Gemini interprets the current message
    Then its response must match Procura's Pydantic extraction schema
    And facts omitted from the current message remain missing

  Scenario: Gemini authorizes deterministic evaluation through function calling
    Given a complete typed procurement request
    When Procura asks Gemini to authorize evaluation
    Then Gemini must call only the procurement-evaluation authorization function
    And Python supplies the fixed supplier, price, authorization, destination, cold-chain, unit, deadline, and ranking sequence

  Scenario: Provider wording is normalized before supplier checks
    Given Gemini extracts Accra as the destination stated by the buyer
    When Procura normalizes the typed request
    Then the deterministic destination becomes Ghana
    And a plural dosage form such as capsules becomes the catalogue form capsule
    And a singular pack unit becomes the canonical unit packs
    And supplier eligibility never depends on a provider guessing the country mapping

  Scenario: Invalid hosted output cannot bypass review
    Given Gemini returns output that does not match the extraction schema
    When the single retry also returns invalid output
    Then Procura creates a human-review case
    And no supplier recommendation or transaction is completed

  Scenario: Provider usage is measured rather than estimated
    Given Gemini returns input and output token metadata
    When Procura stores the workflow trace
    Then Operations reports the measured token total
    And model cost remains unavailable unless a verifiable cost is recorded

  Scenario: A complete buyer request uses one model round trip
    Given Gemini is configured as the hosted language provider
    When a buyer submits every required procurement field in one message
    Then Gemini returns those fields through one typed function call
    And that same function call authorizes the fixed deterministic evaluation
    And Python alone checks suppliers, calculates prices, and ranks eligible quotations
