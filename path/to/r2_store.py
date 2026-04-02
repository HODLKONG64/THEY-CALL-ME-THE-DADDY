class R2Store:
    def __init__(self, settings):
        # Check if the necessary R2 settings are provided
        self.endpoint = settings.get('R2_ENDPOINT', None)
        self.key = settings.get('R2_KEY', None)
        self.bucket = settings.get('R2_BUCKET', None)

        # If endpoint/key/bucket are None, initialize with an empty state
        if not all([self.endpoint, self.key, self.bucket]):
            self.enabled = False  # Disable R2 usage
        else:
            self.enabled = True  # Enable R2 usage
        
        # Initialize any other required resources if needed
        self.setup_resources()  
    
    def setup_resources(self):
        pass  # Setup code if necessary

# MemoryRepository should also reflect that it can work without R2
class MemoryRepository:
    def __init__(self):
        self.state = {}  # Local state for reputation

    def update_reputation(self, new_data):
        # Update reputation using local state
        self.state.update(new_data)
