import time
from main import DelusionistFactory

def auto_run():
    factory = DelusionistFactory()
    
    print("🚀 Starting Automatic Delusionist Loop...")
    
    # We need roughly 50+ iterations. We'll loop until it seems done or max 60.
    for i in range(1, 80):
        print(f"\n🔄 Iteration {i}")
        factory.run()
        
        # Check if done by inspecting the last logged message or state?
        # Simpler: just reload state and check if step is > 3?? 
        # But 'run' doesn't return state. 
        # We can just run; if step 3 is done, it prints "ALL STEPS COMPLETE".
        # Let's simple-loop.
        
        time.sleep(0.5) # Slight breathing room

if __name__ == "__main__":
    auto_run()
