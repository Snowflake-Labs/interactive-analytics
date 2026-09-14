"""Static value pools used to synthesize rows without per-row Faker calls in
the hot path (purchase_transactions). Faker is still used for the small
dimension tables (products/users) where richer text matters more and volume
is low.
"""

CATEGORIES = [
    "Electronics", "Home & Kitchen", "Apparel", "Beauty", "Sports & Outdoors",
    "Toys & Games", "Books", "Automotive", "Grocery", "Health & Wellness",
    "Office Supplies", "Pet Supplies", "Garden & Outdoor", "Jewelry",
    "Baby Products", "Musical Instruments", "Furniture", "Shoes",
    "Luggage & Travel", "Arts & Crafts",
]

SUBCATEGORIES = [
    "Accessories", "Components", "Bundles", "Essentials", "Premium",
    "Budget", "Refurbished", "Limited Edition", "Seasonal", "Clearance",
]

DEPARTMENTS = ["Consumer", "Commercial", "Industrial", "Wholesale"]

BRANDS = [
    "Northwind", "Acme", "Zenith", "Vertex", "Pioneer", "Summit", "Horizon",
    "Cascade", "Meridian", "Aurora", "Frontier", "Beacon", "Apex", "Orbit",
    "Nova", "Element", "Pulse", "Anchor", "Crestline", "Ironwood",
]

MANUFACTURERS = [f"{b} Manufacturing Co." for b in BRANDS]
SUPPLIERS = [f"{b} Global Supply" for b in BRANDS]
SUPPLIER_COUNTRIES = [
    "United States", "China", "Vietnam", "India", "Mexico", "Germany",
    "Bangladesh", "Turkey", "Italy", "South Korea",
]

CURRENCIES = ["USD", "EUR", "GBP", "CAD", "AUD"]
COLORS = [
    "Black", "White", "Gray", "Red", "Blue", "Green", "Yellow", "Orange",
    "Purple", "Pink", "Brown", "Beige", "Silver", "Gold", "Navy",
]
MATERIALS = [
    "Cotton", "Polyester", "Leather", "Aluminum", "Steel", "Plastic",
    "Wood", "Glass", "Ceramic", "Rubber", "Nylon", "Wool", "Bamboo",
]
SIZES = ["XS", "S", "M", "L", "XL", "XXL", "One Size", "N/A"]
SEASONS = ["Spring", "Summer", "Fall", "Winter", "All-Season"]
GENDERS = ["Male", "Female", "Unisex"]
AGE_GROUPS = ["Infant", "Toddler", "Kids", "Teen", "Adult", "Senior", "All Ages"]
WAREHOUSE_LOCATIONS = [
    "US-EAST-1", "US-WEST-1", "US-CENTRAL-1", "EU-WEST-1", "EU-CENTRAL-1",
    "APAC-SOUTHEAST-1", "APAC-NORTHEAST-1",
]

ACCOUNT_STATUSES = ["active", "inactive", "suspended", "pending", "closed"]
LOYALTY_TIERS = ["Bronze", "Silver", "Gold", "Platinum", "None"]
ACQUISITION_CHANNELS = [
    "organic_search", "paid_search", "social_media", "email", "referral",
    "direct", "affiliate", "display_ads",
]
UTM_SOURCES = ["google", "facebook", "instagram", "tiktok", "bing", "newsletter", "twitter"]
UTM_MEDIUMS = ["cpc", "organic", "social", "email", "referral", "display"]
UTM_CAMPAIGNS = [
    "spring_sale", "summer_clearance", "black_friday", "cyber_monday",
    "new_arrivals", "loyalty_rewards", "flash_sale", "holiday_2025",
]
DEVICE_TYPES = ["desktop", "mobile", "tablet"]
OS_LIST = ["iOS", "Android", "Windows", "macOS", "Linux"]
BROWSERS = ["Chrome", "Safari", "Firefox", "Edge", "Samsung Internet"]
LANGUAGES = ["en", "es", "fr", "de", "pt", "zh", "ja", "ko"]
INCOME_BANDS = ["<25k", "25k-50k", "50k-75k", "75k-100k", "100k-150k", "150k+"]
OCCUPATIONS = [
    "Engineer", "Teacher", "Nurse", "Manager", "Sales Rep", "Consultant",
    "Designer", "Analyst", "Student", "Retired", "Self-Employed", "Other",
]
EDUCATION_LEVELS = ["High School", "Some College", "Bachelor's", "Master's", "Doctorate"]
CREDIT_SCORE_BANDS = ["Poor", "Fair", "Good", "Very Good", "Excellent"]

ORDER_STATUSES = ["pending", "processing", "shipped", "delivered", "cancelled", "returned"]
FULFILLMENT_STATUSES = ["unfulfilled", "partially_fulfilled", "fulfilled", "backordered"]
PAYMENT_STATUSES = ["pending", "authorized", "paid", "failed", "refunded", "partially_refunded"]
PAYMENT_METHODS = [
    "credit_card", "debit_card", "paypal", "apple_pay", "google_pay",
    "gift_card", "bank_transfer", "buy_now_pay_later",
]
SALES_CHANNELS = ["web", "mobile_app", "marketplace", "retail_store", "phone", "b2b_portal"]
SHIPPING_METHODS = ["standard", "expedited", "overnight", "same_day", "pickup"]
SHIPPING_CARRIERS = ["UPS", "FedEx", "USPS", "DHL", "Amazon Logistics", "Local Courier"]
RETURN_REASONS = [
    "wrong_size", "defective", "not_as_described", "changed_mind",
    "arrived_late", "better_price_found", "damaged_in_transit",
]
COUNTRIES = [
    "United States", "Canada", "United Kingdom", "Germany", "France",
    "Australia", "Japan", "Brazil", "India", "Mexico", "Spain", "Italy",
    "Netherlands", "Sweden", "South Korea",
]
