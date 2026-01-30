#!/usr/bin/env python3
import json
import glob
import os
import statistics

def analyze():
    # Path to processed files
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data/processed/interactions")
    files = glob.glob(os.path.join(data_dir, "*.turn_based.json"))
    
    valid_samples = []
    
    print(f"Total files found: {len(files)}")
    
    for fpath in files:
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            turns = data.get('turns', [])
            num_turns = len(turns)
            
            # Filter logic: Remove if turns <= 2 or turns >= 70
            # Keeping 2 < turns < 70
            if num_turns <= 2 or num_turns >= 70:
                continue
                
            # Collect stats
            verification = data.get('verification', {})
            similarity = verification.get('similarity', 0.0)
            perfect_match = verification.get('perfect_match', False)
            
            # Action confidence
            confidences = []
            for t in turns:
                action = t.get('action', {})
                if 'confidence' in action:
                    confidences.append(action['confidence'])
            
            # Calculate average confidence for this sample
            avg_confidence = statistics.mean(confidences) if confidences else 0.0
            
            valid_samples.append({
                'file': fpath,
                'similarity': similarity,
                'perfect_match': perfect_match,
                'avg_confidence': avg_confidence
            })
            
        except Exception as e:
            print(f"Error reading {fpath}: {e}")

    print(f"Files after filtering (2 < turns < 70): {len(valid_samples)}")
    
    if not valid_samples:
        print("No samples matched the criteria.")
        return

    # Extract lists
    similarities = [s['similarity'] for s in valid_samples]
    confidences = [s['avg_confidence'] for s in valid_samples]
    perfect_matches = [s for s in valid_samples if s['perfect_match']]
    
    print("\n" + "="*40)
    print("Perfect Match Statistics")
    print("="*40)
    print(f"Perfect Matches: {len(perfect_matches)}")
    print(f"Perfect Match Ratio: {len(perfect_matches)/len(valid_samples):.2%}")
    
    # 相似度阈值分布
    print("\n" + "="*40)
    print("Similarity Threshold Distribution")
    print("="*40)
    thresholds = [0.99, 0.95, 0.90, 0.80]
    for t in thresholds:
        count = sum(1 for s in valid_samples if s['similarity'] >= t)
        print(f"  similarity >= {t:.0%}: {count} ({count/len(valid_samples):.2%})")
    
    def print_dist(name, values):
        if not values:
            return
        print(f"\n{name} Distribution:")
        print(f"  Count: {len(values)}")
        print(f"  Mean:  {statistics.mean(values):.4f}")
        try:
            if len(values) > 1:
                print(f"  Std:   {statistics.stdev(values):.4f}")
        except:
            pass
        print(f"  Min:   {min(values):.4f}")
        
        try:
            quantiles = statistics.quantiles(values, n=4)
            print(f"  25%:   {quantiles[0]:.4f}")
            print(f"  50%:   {quantiles[1]:.4f}")
            print(f"  75%:   {quantiles[2]:.4f}")
        except AttributeError:
             # Fallback for older python if needed, though 3.8+ has it
             pass
             
        print(f"  Max:   {max(values):.4f}")

    print("\n" + "="*40)
    print("Confidence Distribution (Sample Averages)")
    print("="*40)
    print_dist("Avg Confidence", confidences)
    
    print("\n" + "="*40)
    print("Similarity Distribution")
    print("="*40)
    print_dist("Similarity", similarities)

if __name__ == "__main__":
    analyze()
