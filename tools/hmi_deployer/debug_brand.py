import sys
sys.path.insert(0, '/mnt/c/Users/hithe/Documents/MIL-HMI-PROJ/swarm/w5-b2-sim')
from designer.model import DesignerProject, DesignerPage
from designer.layout.compiler import compile_page
import json

from test_w5_b2_designer_sim import PLAN, _reply

project = DesignerProject.from_dict(PLAN)
project.brand = {"logos": [], "accent": "#22c55e"}
report = compile_page(project, project.pages[0], project.pages[0].widgets[0] if project.pages[0].widgets else None)
for w in project.pages[0].walk():
    if w.id == "screenTitle":
        print("screenTitle color:", w.properties.get("color"))