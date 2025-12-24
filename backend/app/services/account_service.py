class AccountService:
    def __init__(self, session):
        self.session = session

    async def get_equity_usd(self, account_id: str) -> float:
        # Demo: static equity
        return 100000.0
