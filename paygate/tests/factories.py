

class MockResponse:
    """
    A mocked requests response.
    """

    def __init__(self, json_data=None, status_code=200):
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        """
        The Json output that will be mocked
        """
        return self.json_data

    def content(self):
        """
        The Json data
        """
        return self.json_data
