# Zelle setup

The checkout displays Zelle instructions and creates a pending manual order.

Render environment variable:

ZELLE_RECIPIENT=713-378-1730

Workflow:
1. Customer sends the total by Zelle and uses the order number as the memo.
2. Photographer verifies the deposit in the banking app.
3. In Photographer Dashboard > Orders, change the order to `paid`.
4. The customer receives an email and the private order page unlocks downloads.
