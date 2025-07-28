from aiogram.fsm.state import State, StatesGroup

class UserStates(StatesGroup):
    MAIN_MENU = State()
    BROWSING_CATEGORIES = State()
    BROWSING_PRODUCTS = State()
    VIEWING_PRODUCT = State()
    SELECTING_LOCATION = State()
    PAYMENT_WAITING = State()
    PAYMENT_CHECKING = State()
    VIEWING_HISTORY = State()
    WRITING_REVIEW = State()
    ENTERING_PROMO = State()

class AdminStates(StatesGroup):
    ADMIN_MENU = State()
    ADDING_CATEGORY = State()
    ADDING_PRODUCT = State()
    ADDING_LOCATION = State()
    EDITING_CONTENT = State()
    EDITING_ABOUT = State()
    MANAGE_CATEGORIES = State()
    MANAGE_PRODUCTS = State()
    MANAGE_LOCATIONS = State()
    EDITING_CATEGORY = State()
    EDITING_PRODUCT = State()
    EDITING_LOCATION = State()
    ADDING_PROMO = State()
    MANAGE_PROMOS = State()
    EDITING_PROMO = State()
    VIEWING_REVIEWS = State()


