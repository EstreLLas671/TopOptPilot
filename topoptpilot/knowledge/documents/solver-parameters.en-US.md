# MATLAB solver parameters and fidelities

`volfrac`, `penal`, `rmin`, `beta` and `max_iter` are compiled by Policy. Step1 is coarse Python 2D, Step2 adaptive coarse Python 2D, Step3 coarse Python 3D and Step4 full-grid MATLAB 3D. Each authorization runs one experiment and stops for a result decision; Step4 never falls back to Python.
