from .database import init_db

# This will be expanded with simulation logic and API routers

def setup():
    init_db()

if __name__ == "__main__":
    setup()
    print("Database initialized.")
