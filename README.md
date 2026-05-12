# Gridfinity Workbench

Fork of https://github.com/Stu142/FreeCAD-Gridfinity-Workbench.

It adds an alternative Clickfinity-style baseplate workflow via base parameters.

This Clickfinity variant is tuned for simpler, more reliable 3D printing with reduced number of retracts.

This fork is adapted to work with FreeCAD LinkStable (single commit).

![Clickfinity versions](clickfinity_versions.jpg)


# Design principles

### Baseplate

* Main grid size is square, 42 mm
* It defines baseplate sizing
* Basic dimensions for baseplate profile are half width (2.15 mm) and height (2.5 mm) with 45° chamfer on top
* Lower chamfer for baseplate made optional with 0.7 mm size
* Outer fillet radius is taken from bin outer radius, 4 mm

### Bins

* Bins are defined from baseplates
* Clearance (0.25 mm) defines how much bins are in-set from four horizontal directions
* Otherwise bin profile completely duplicates baseplate profile

### Generic

* Fillets are mostly calculated from the Bin Outer Radius to keep walls thickness constant
* Some features, like clips, use proportional calculations to main profile sizes


### Reference design by @willtree8

Some of the dimensions are different from what is used in this implementation.

![Spec drawing from @willtree8](spec_draft_willtree8.jpg)
