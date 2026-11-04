import os, runpy, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Blender", "BrutalLegend"))
runpy.run_module("Brutal", run_name="__main__")
