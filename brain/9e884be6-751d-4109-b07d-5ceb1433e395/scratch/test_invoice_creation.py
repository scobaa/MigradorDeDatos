import xmlrpc.client

url = "https://tes-importaciones.cloudpepper.site"
db = "tes-importaciones.cloudpepper.site"
username = "admin"
password = "1234"

print("Connecting...")
common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
uid = common.authenticate(db, username, password, {})
models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

print("Checking partners...")
partners = models.execute_kw(
    db, uid, password,
    "res.partner", "search_read",
    [[("customer_rank", ">", 0)]], {"fields": ["id", "name"], "limit": 1}
)
print("Partners found:", partners)

print("Checking products...")
products = models.execute_kw(
    db, uid, password,
    "product.product", "search_read",
    [[]], {"fields": ["id", "name"], "limit": 1}
)
print("Products found:", products)

if partners and products:
    partner_id = partners[0]["id"]
    product_id = products[0]["id"]
    
    print(f"Testing invoice creation for partner {partner_id} and product {product_id}...")
    try:
        # Create draft invoice
        move_vals = {
            "move_type": "out_invoice",
            "partner_id": partner_id,
            "invoice_date": "2026-05-26",
            "name": "TEST-INV-9999",  # Historical invoice number
            "invoice_line_ids": [
                (0, 0, {
                    "product_id": product_id,
                    "name": "Test line description",
                    "quantity": 2.0,
                    "price_unit": 25.0,
                })
            ]
        }
        move_id = models.execute_kw(
            db, uid, password,
            "account.move", "create",
            [move_vals]
        )
        print(f"Draft invoice created with ID: {move_id}")
        
        # Read the invoice state and name
        move = models.execute_kw(
            db, uid, password,
            "account.move", "read",
            [[move_id]], {"fields": ["name", "state", "amount_total"]}
        )
        print("Draft details:", move)
        
        # Post the invoice
        print("Posting invoice...")
        models.execute_kw(
            db, uid, password,
            "account.move", "action_post",
            [[move_id]]
        )
        
        # Read details again
        posted_move = models.execute_kw(
            db, uid, password,
            "account.move", "read",
            [[move_id]], {"fields": ["name", "state", "amount_total"]}
        )
        print("Posted details:", posted_move)
        
        # Delete or keep it
        print("Unlinking test invoice (moving to draft first since posted cannot be deleted)...")
        models.execute_kw(
            db, uid, password,
            "account.move", "button_draft",
            [[move_id]]
        )
        models.execute_kw(
            db, uid, password,
            "account.move", "unlink",
            [[move_id]]
        )
        print("Test completed successfully and cleaned up!")
        
    except Exception as e:
        print("Error during invoice test:", e)
else:
    print("Could not run test because no partners/products were found.")
