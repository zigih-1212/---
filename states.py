from aiogram.fsm.state import State, StatesGroup

class OnboardingStates(StatesGroup):
    waiting_role = State()
    waiting_channel = State()
    waiting_source_channel = State()
    waiting_saas_tg_channel = State()

class AdminStates(StatesGroup):
    broadcast_text = State()
    extend_user_id = State()
    extend_days = State()

class SaasStates(StatesGroup):
    waiting_apikey = State()
    waiting_erid_override = State()
    waiting_promocode = State()
    choosing_channel_for_promo = State()

class PaymentFSM(StatesGroup):
    choosing_tariff = State()
    choosing_method = State()
    waiting_for_receipt = State()
    waiting_promocode = State()
    choosing_channel_for_promo = State()

class PayoutStates(StatesGroup):
    waiting_for_card = State()
    waiting_for_amount = State()
