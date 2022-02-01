import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from scipy.interpolate import RegularGridInterpolator
from matplotlib import colors
import matplotlib.patches as mpatches
import cv2

# Model
ITERATIONS = 1000
SNAP_INTERVAL = 1
SNAPSHOTS = (ITERATIONS - 1)//SNAP_INTERVAL + 1

# LBM parameters
c = np.array([(0, 0), (1, 0), (0, 1), (-1, 0), (0, -1), (1, 1),
              (-1, 1), (-1, -1), (1, -1)])
w = np.array([4/9, 1/9, 1/9, 1/9, 1/9, 1/36, 1/36, 1/36, 1/36])
Q = 9

AIR, WALL, INLET, OUTLET, INFECTED, SUSCEPTIBLE = [0, 1, 2, 3, 4, 5]

# for know hardcoden
susceptible_centroids = np.array([(18,93), (79,80), (79,51), (80,26), (49,5)])
NUM_SUSCEP_CENTROIDS = len(susceptible_centroids)

class LBM:
    def __init__(self, size=100, map_name='concept1', particles=True,
                inlet_handler=None, outlet_handler=None, init="default"):
        # Get the map details
        self.width = self.height = size
        self.map_scaling_factor = 1.0
        wall, inlet, outlet, infected, susceptible = \
            self.read_map_from_file('./maps/' + map_name)

        assert wall.shape == inlet.shape == outlet.shape

        self.wall = wall
        self.inlet = inlet
        self.outlet = outlet
        self.infected = infected
        self.susceptible = susceptible

        # Whether or not particles need to be simulated.
        self.particles = particles

        # every 20 it spawn particles
        if self.particles:
            self.spawn_rate = 20             # every x iterations
            self.spawn_amount_at_rate = 1   # x particles

            self.num_particles = (ITERATIONS//self.spawn_rate) * self.spawn_amount_at_rate
            self.particle_nr = 0

        self.inlet_handler = inlet_handler if inlet_handler is not None else \
            LBM.inlet_handler
        self.outlet_handler = outlet_handler if outlet_handler is not None \
            else LBM.outlet_handler

        if init == "default":
            self.init_default()
        elif init == "cavity":
            self.init_liddrivencavity()

        print("=" * 10 + " Model values " + "=" * 10)
        print(f"dx {self.dx:.4f} m/unit")
        print(f"dt {self.dt:.4f} s/step")
        print(f"Tau {self.tau:.4f} m^2/s")
        print(f"Re {self.Re:.4f}")
        print(f"nu_lb {self.nu_lb:.4f} m^2/s")
        print(f"u_lb {self.u_lb:.4f} units/step")

        # Set the initial macroscopic quantities
        self.rho = np.ones((self.width, self.height))
        self.ux = np.full((self.width, self.height), 0.0)

        self.uy = np.zeros((self.width, self.height))

        self.f = self.get_equilibrium(self.width * self.height,
                                     self.rho.flatten(), self.ux.flatten(),
                                     self.uy.flatten()).reshape(
            (self.width, self.height, Q))

    def init_default(self):
        total_time = (ITERATIONS * 2.5 / 500) * 60 # s

        # Known parameters (SI units)
        self.L_p = 1        # m
        self.nu_p = 1.48e-5 # m^2/s
        self.u_p = 1        # m/s
        self.dt = total_time / ITERATIONS       # s

        # Compute other variables
        self.dx = self.L_p / self.width
        self.Re = (self.u_p * self.L_p) / self.nu_p
        self.u_lb = self.u_p * (self.dt / self.dx)
        self.L_lb = self.L_p / self.dx
        self.nu_lb = (self.u_lb * self.L_lb) / self.Re

        self.cssq = 1/3
        self.tau = self.nu_lb / self.cssq + 0.5

    def init_liddrivencavity(self, Re=100.0):
        # Known parameters (SI units)
        self.Re = Re
        self.L_lb = self.width
        self.L_p = 1        # m
        self.u_p = 1        # m/s
        self.u_lb = 0.2

        # Compute other variables
        self.dx = self.L_p / self.L_lb
        self.nu_lb = (self.u_lb * self.L_lb) / self.Re
        self.dt = self.Re * self.nu_lb / self.L_lb**2       # s

        self.cssq = 1/3
        self.tau = self.nu_lb / self.cssq + 0.5

    def read_map_from_file(self, filename):
        with open(filename, 'r') as f:
            iterator = enumerate(f)
            _, firstline = next(iterator)
            width, height = [int(x) for x in firstline.strip().split(',')]
            assert width == height, "Map width does not match map height"
            self.map_scaling_factor = self.width / width

            wall = np.zeros((width, height), bool)
            inlet = np.zeros((width, height), bool)
            outlet = np.zeros((width, height), bool)
            infected = np.zeros((width, height), bool)
            susceptible = np.zeros((width, height), bool)

            for i, line in iterator:
                for j, c in enumerate(line.strip()):
                    c = int(c)
                    if c == WALL:
                        wall[j, width-i] = True
                    elif c == INLET:
                        inlet[j, width-i] = True
                    elif c == OUTLET:
                        outlet[j, width-i] = True
                    elif c == INFECTED:
                        infected[j, width-i] = True
                    elif c == SUSCEPTIBLE:
                        susceptible[j, width-i] = True

        # Resize all the arrays
        wall = cv2.resize(wall.astype('uint8'), (self.width, self.height), cv2.INTER_NEAREST).astype(bool)
        inlet = cv2.resize(inlet.astype('uint8'), (self.width, self.height), cv2.INTER_NEAREST).astype(bool)
        outlet = cv2.resize(outlet.astype('uint8'), (self.width, self.height), cv2.INTER_NEAREST).astype(bool)
        infected = cv2.resize(infected.astype('uint8'), (self.width, self.height), cv2.INTER_NEAREST).astype(bool)
        susceptible = cv2.resize(susceptible.astype('uint8'), (self.width, self.height), cv2.INTER_NEAREST).astype(bool)

        return wall, inlet, outlet, infected, susceptible

    def moment_update(f):
        """
        Update the rho and velocity values of each grid position.
        """
        rho = np.sum(f, 2)

        ux = np.sum(c[:, 0] * f, axis=2) / rho
        uy = np.sum(c[:, 1] * f, axis=2) / rho

        return rho, ux, uy

    def get_equilibrium(self, n, rho, ux, uy):
        """
        Calculate the equalibrium distribution for the BGK operator.
        """
        udotu = ux * ux + uy * uy

        udotc = np.zeros((n, Q), dtype=float)
        for i in range(Q):
            udotc[:, i] = ux * c[i, 0] + uy * c[i, 1]

        f_eq = np.zeros((n, 9), dtype=float)

        for i in range(Q):
            f_eq[:, i] = w[i] * rho * (1 + udotc[:, i] / self.cssq +
                                       (udotc[:, i])**2 / (2 * self.cssq**2) -
                                       udotu / (2 * self.cssq))

        return f_eq

    def lbm_iteration(self, it):
        """
        Perform an iteration of the Lattice-Boltzmann method.
        """
        # moment update
        self.rho, self.ux, self.uy = LBM.moment_update(self.f)

        # equilibrium
        f_eq = self.get_equilibrium(self.width * self.height,
                                   self.rho.flatten(), self.ux.flatten(),
                                   self.uy.flatten()).reshape(
                                       (self.width, self.height, Q))

        # Check stability condition
        assert np.min(f_eq) >= 0 ,f"Simulation violated stability condition at {np.unravel_index(np.argmin(f_eq), f_eq.shape)}"

        # collision
        self.f = self.f * (1 - (1 / self.tau)) + (1 / self.tau) * f_eq
        # self.f = self.f * (1 - (self.dt / self.tau)) + (self.dt / self.tau) * f_eq

        # streaming
        for i in range(Q):
            self.f[:, :, i] = np.roll(self.f[:, :, i], c[i], axis=(0, 1))

        # bounce back
        self.ux[self.wall] = 0
        self.uy[self.wall] = 0

        boundary_f = self.f[self.wall, :]
        boundary_f = boundary_f[:, [0, 3, 4, 1, 2, 7, 8, 5, 6]]
        self.f[self.wall, :] = boundary_f

        # Handle inlets and outlets. Note that "self.inlet_handler" does not
        # necessarily refer to LBM.inlet_handler, it could also be a custom
        # callback function provided by the user when initialising the model.
        self.inlet_handler(self, it)
        self.outlet_handler(self)

    def inlet_handler(model, it):
        """
        The default inlet handler for an LBM model.
        """
        # Set the velocity vector at inlets
        period = 50
        # model.u_lb *= (0.5 * np.sin(2 * np.pi * it/period) + 0.1)
        # model.u_lb *= (0.4 * np.sin(2 * np.pi * it/period) + 0.2)

        inlet_ux = model.u_lb
        inlet_uy = 0.0
        inlet_rho = np.ones_like(model.rho[model.inlet], dtype=float)

        model.f[model.inlet] = model.get_equilibrium(len(inlet_rho),
                                                 inlet_rho,
                                                 inlet_ux, inlet_uy)

    def outlet_handler(model):
        """
        The default outlet handler for an LBM model.
        """
        # Set the density at outlets
        outlet_rho = model.rho[model.outlet]
        outlet_ux = model.ux[model.outlet]
        outlet_uy = model.uy[model.outlet]
        model.f[model.outlet] = model.get_equilibrium(len(outlet_ux), outlet_rho,
                                                    outlet_ux, outlet_uy)

    def render(self, kind="density", vectors=False, save_file=None):
        """
        Render the values collected by the model with matplotlib. Argument
        "kind" should be of value "density" or "mag"
        """
        # Initialize plots
        fig, ax = plt.subplots()

        # First layer: fluid plot
        vmin = 0 if kind == "mag" else 0.8
        vmax = 0.2 if kind == "mag" else 1.2

        self.fluid_plot = plt.imshow(np.zeros((self.width, self.height),
                                              dtype=float),
                                     vmin=0.0, vmax=self.u_lb,
                                     cmap=plt.get_cmap("jet"))
        cbar = plt.colorbar(self.fluid_plot)
        cbar.set_label("Air speed (m/s)", rotation=270, labelpad=15)

        for idx,val in enumerate(susceptible_centroids):
          x,y = val
          plt.text(x, y, str(idx), fontsize = 10, color='white')

        # Second layer: vector plot
        if vectors:
            x, y = np.meshgrid(np.linspace(0, self.width-1, 20, dtype=int),
                               np.linspace(0, self.height-1, 20, dtype=int))
            u = self.ux[x, y]
            v = self.uy[x, y]

            # Set scale to 0.5 for lid driven cavity, 4 for Karman vortex
            self.vector_plot = plt.quiver(x, y, u, v, scale=4)

        # Third layer: particle plots
        if self.particles:
            self.particle_locations = np.zeros((self.num_particles, 2), float)
            self.particle_plots = [plt.plot(0, 0, 'ro', markersize=2)[0]
                                   for i in range(self.num_particles)]

        # Fourth layer: map plot
        map_data = (WALL * self.wall + INLET * self.inlet +
                    OUTLET * self.outlet + INFECTED * self.infected +
                    SUSCEPTIBLE * self.susceptible)

        clr = ["lightgreen", "blue", "red", "purple", "yellow", "darkgreen"]
        cmap = colors.ListedColormap(clr)

        self.map_plot = plt.imshow(map_data.T, alpha=0.6, origin="lower",
                                   cmap=cmap)

        patches = [mpatches.Patch(color=c, label=name) for c, name in
                   zip(clr[1:],
                       ['Wall', 'Inlet', 'Outlet', 'Infected', 'Susceptible'])]

        ax.legend(handles=patches, loc='upper center',
                  bbox_to_anchor=(0.5, -0.05), fancybox=True, shadow=True,
                  ncol=len(clr))
        fig.tight_layout()

        if self.particles:
            # Initialise particles
            self.infections = np.zeros((NUM_SUSCEP_CENTROIDS, ITERATIONS))
            self.removed = np.zeros((ITERATIONS))
            self.particles_exited = set()

        anim = FuncAnimation(fig, self.animate, interval=1, frames=ITERATIONS,
                             repeat=True, fargs=[ax, kind, vectors])

        if save_file:
            anim.save("_"  + ".html",  writer="html")

            # for i in range(ITERATIONS):
            #     self.animate(i, ax, kind, vectors)
            #     fig.savefig('simulation/concept2/' + str(i) +  '.png')
        else:
            for i in range(ITERATIONS):
                self.animate(i, ax, kind, vectors)

        if self.particles:
            fig, ax = plt.subplots()

            infection_rate = np.cumsum(self.infections, axis=1)
            removed_rate = np.cumsum(self.removed)

            print(infection_rate)
            ax.plot(infection_rate.T)
            # ax.legend(susceptible_centroids)
            fig.savefig('infection_rate.png')
            ax.plot(removed_rate)
            fig.savefig('removed_rate.png')


    def animate(self, it, ax, kind, vectors):
        print("Running animate on iteration {} of {} of kind {}".format(it, ITERATIONS, kind),
              end="\r")
        # Perform an LBM iteration and update fluid plot
        self.lbm_iteration(it)

        vals = np.sqrt(self.ux**2 + self.uy**2) if kind == "mag" else self.rho
        self.fluid_plot.set_data(vals.T)

        # Update the vector plot
        if vectors:
            x, y = np.meshgrid(np.linspace(0, self.width-1, 20, dtype=int),
                               np.linspace(0, self.height-1, 20, dtype=int))
            u, v = self.ux[x, y], self.uy[x, y]

            self.vector_plot.set_UVC(u, v)

        # Update particle locations and plots
        if self.particles:
            self.update_particles(it)

            for i, loc in enumerate(self.particle_locations):
                self.particle_plots[i].set_data(*loc)

        # Update the plot title
        ax.set_title("{}, iteration {}".format(kind, it))


    def update_particles(self, it):
        """
        Tracks the motions of particles through the airflow.
        """

        if it % self.spawn_rate == 0:
            for _ in range(self.spawn_amount_at_rate):
                # Spawn a new particle
                # Randomly choose an infected cell.

                if self.particle_nr < self.num_particles:

                    infected_indices = np.where(self.infected)
                    idx = np.random.randint(len(infected_indices[0]))

                    self.particle_locations[self.particle_nr] = \
                        infected_indices[0][idx], infected_indices[1][idx]
                    self.particle_nr += 1
                    # print("part", self.particle_nr)

        # it > 0
        ux_func = RegularGridInterpolator((np.arange(self.width),
                                           np.arange(self.height)),
                                          self.ux)

        uy_func = RegularGridInterpolator((np.arange(self.width),
                                           np.arange(self.height)),
                                          self.uy)

        # Add the linearly interpolated velocity vector to the location of
        # the point.
        for i in range(self.particle_nr):
            x, y = self.particle_locations[i]
            # check whether particle intercepted a person

            if i in self.particles_exited:
                continue

            if self.susceptible[int(round(x)), int(round(y))]:

                try:
                    # FIND CLOSEST NODE
                    node= int(x), int(y)
                    nodes = susceptible_centroids
                    dist_2 = np.sum((nodes - node)**2, axis=1)
                    closest = np.argmin(dist_2)

                    self.infections[closest][i] += 1
                except:
                    # gebeurde een keer, bij 2000 kunnen we best 1 particle missen
                    print("Idk!!!!!!!")
                    pass

                self.particles_exited.add(i)
                self.particle_locations[i] = [0, 0]
            elif self.outlet[int(round(x)), int(round(y))]:
                self.removed[i] += 1
                self.particles_exited.add(i)
                self.particle_locations[i] = [0, 0]
            else:
                dx, dy = ux_func([x, y])[0], uy_func([x, y])[0]

                speed_factor = self.map_scaling_factor

                dx, dy = speed_factor*dx, speed_factor*dy
                # Keep particles inside boundaries
                new_x = min(max(0, x + dx), self.width - 1)
                new_y = min(max(0, y + dy), self.height - 1)

                self.particle_locations[i] = [new_x, new_y]


if __name__ == '__main__':
    model = LBM(map_name='liddrivencavity', particles=False, init="cavity")

    model.render(kind="mag", vectors=True, save_file='animation')
