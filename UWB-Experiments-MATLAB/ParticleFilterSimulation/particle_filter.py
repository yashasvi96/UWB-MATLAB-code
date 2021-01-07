# ------------------------------------------------------------------------
# coding=utf-8
# ------------------------------------------------------------------------
#
#  Created by Martin J. Laubach on 2011-11-15
#
# ------------------------------------------------------------------------

from __future__ import absolute_import

from typing import (Dict, List, Tuple, Set)

import random
import math
import bisect
import numpy as np
from scipy.stats import multivariate_normal
from draw import Maze

import time

"""
# Smaller maze

maze_data = ( ( 2, 0, 1, 0, 0 ),
              ( 0, 0, 0, 0, 1 ),
              ( 1, 1, 1, 0, 0 ),
              ( 1, 0, 0, 0, 0 ),
              ( 0, 0, 2, 0, 1 ))
"""

# 0 - empty square
# 1 - occupied square
# 2 - occupied square with a beacon at center, detectable by the robot

# maze_data = ( ( 1, 1, 0, 0, 2, 0, 0, 0, 0, 1 ),
#               ( 1, 2, 0, 0, 1, 1, 0, 0, 0, 0 ),
#               ( 0, 1, 1, 0, 0, 0, 0, 1, 0, 1 ),
#               ( 0, 0, 0, 0, 1, 0, 0, 1, 1, 2 ),
#               ( 1, 1, 0, 1, 1, 2, 0, 0, 1, 0 ),
#               ( 1, 1, 1, 0, 1, 1, 1, 0, 2, 0 ),
#               ( 2, 0, 0, 0, 0, 0, 0, 0, 0, 0 ),
#               ( 1, 2, 0, 1, 1, 1, 1, 0, 0, 0 ),
#               ( 0, 0, 0, 0, 1, 0, 0, 0, 1, 0 ),
#               ( 0, 0, 1, 0, 0, 2, 1, 1, 1, 0 ))

maze_data = ( ( 3, 0, 0, 0, 0, 0, 0, 0, 0, 3 ),
              ( 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 ),
              ( 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 ),
              ( 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 ),
              ( 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 ),
              ( 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 ),
              ( 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 ),
              ( 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 ),
              ( 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 ),
              ( 3, 0, 0, 0, 0, 0, 0, 0, 0, 3 ))

anchor_list = [('C584',0.37,0.20,0.78), ('DA36',0.21,3.35,1.29), ('9234',2.95,2.78,1.18), ('8287',2.69,0.36,0.66)] # unit in m
anchor_list = [('C584',37,20,78), ('DA36',21,335,129), ('9234',295,278,118), ('8287',269,36,66)] # unit in cm
PARTICLE_COUNT = 2000    # Total number of particles

ROBOT_HAS_COMPASS = False # Does the robot know where north is? If so, it
# makes orientation a lot easier since it knows which direction it is facing.
# If not -- and that is really fascinating -- the particle filter can work
# out its heading too, it just takes more particles and more time. Try this
# with 3000+ particles, it obviously needs lots more hypotheses as a particle
# now has to correctly match not only the position but also the heading.

# ------------------------------------------------------------------------
# Some utility functions

def add_noise(level, *coords):
    if isinstance(coords[0], list):
        return [x + random.uniform(-level, level) for x in coords[0]]
    return [x + random.uniform(-level, level) for x in coords]

def add_little_noise(*coords):
    return add_noise(5, *coords)

def add_some_noise(*coords):
    return add_noise(10, *coords)

# This is just a gaussian kernel I pulled out of my hat, to transform
# values near to robbie's measurement => 1, further away => 0
sigma = 5
sigma2 = sigma ** 2
def w_gauss(a, b):
    error = a - b
    g = math.e ** -(error ** 2 / (2 * sigma2))
    return g

# This is the 0-mean multivariate gaussian pdf value serves as the weight
# values near to robbie's measurement => 1, further away => 0
# the pdf value is not normalized
def w_gauss_multi(a: List, b: List) -> float:
    a = np.asarray(list(filter(lambda x: x != float('inf'), a)))
    b = np.asarray(list(filter(lambda x: x != float('inf'), b)))
    assert len(a) == len(b)
    dim = len(a)
    if dim > 0:
        error = (a - b)
        error = error.reshape(1,dim)
        mean = np.zeros(dim, float)
        cov = np.zeros((dim,dim), float)
        np.fill_diagonal(cov, sigma2)
        g = multivariate_normal.pdf(x=error, mean=mean, cov=cov)
        return g


# ------------------------------------------------------------------------
def compute_mean_point(world, particles, dist_threshold=25):
    """
    Compute the mean for all particles that have a reasonably good weight.
    This is not part of the particle filter algorithm but rather an
    addition to show the "best belief" for current position.
    """

    m_x, m_y, m_count = 0, 0, 0
    for p in particles:
        m_count += p.w
        m_x += p.x * p.w
        m_y += p.y * p.w

    if m_count == 0:
        return -1, -1, False

    m_x /= m_count
    m_y /= m_count

    # Now compute how good that mean is -- check how many particles
    # actually are in the immediate vicinity
    m_count = 0
    for p in particles:
        if world.euclidean_dist(p.x, p.y, m_x, m_y) < dist_threshold:
            m_count += 1

    return m_x, m_y, m_count > PARTICLE_COUNT * 0.95

# ------------------------------------------------------------------------
class WeightedDistribution(object):
    def __init__(self, state):
        accum = 0.0
        self.state = [p for p in state if p.w > 0]
        self.distribution = []
        for x in self.state:
            accum += x.w
            self.distribution.append(accum)

    def pick(self):
        try:
            uni = random.uniform(0, 1)
            idx = bisect.bisect_left(self.distribution, uni)
            a = self.state[idx]
            return a
        except IndexError:
            # Happens when all particles are improbable w=0
            return None

# ------------------------------------------------------------------------
class Particle(object):
    def __init__(self, x, y, heading=None, w=1, noisy=False):
        if heading is None:
            heading = random.uniform(0, 360)
        if noisy:
            x, y, heading = add_some_noise(x, y, heading)

        self.x = x
        self.y = y
        self.h = heading
        self.w = w

    def __repr__(self):
        return "(%f, %f, w=%f)" % (self.x, self.y, self.w)

    @property
    def xy(self):
        return self.x, self.y

    @property
    def xyh(self):
        return self.x, self.y, self.h

    @classmethod
    def create_random_particles(cls, particle_count, maze):
        return [cls(*maze.random_free_place()) for _ in range(0, particle_count)]

    def read_nearest_sensor(self, maze):
        """
        Find distance to nearest beacon.
        """
        return maze.distance_to_nearest_beacon(*self.xy)
    
    def read_sensors(self, maze):
        """
        Find all distances to all available beacons.
        """
        return maze.distances_to_all_beacons(*self.xy)
        # if not specified_idx:
        #     return readings
        # if specified_idx:
        #     # Choose specified sensors within all t
        #     # positive infinity in readings indicates signal loss - the beacon 
        #     # is not reachable
        #     for i in specified_idx:
        #         readings[i] = float('inf')
        #     return readings

    def advance_by(self, speed, delta_t=1, checker=None, noisy=False):
        h = self.h
        if noisy:
            speed, h = add_little_noise(speed, h)
            h += random.uniform(-15, 15) # needs more noise to disperse better
        r = math.radians(h)
        dx = math.sin(r) * speed * delta_t
        dy = math.cos(r) * speed * delta_t
        # if checker is None or checker(self, dx, dy):
        #     self.move_by(dx, dy)
        #     return True
        # return False

    def move_by(self, x, y):
        self.x += x
        self.y += y

# ------------------------------------------------------------------------
class Robot(Particle):
    speed = 0

    def __init__(self, maze):
        super(Robot, self).__init__(*maze.random_free_place(), heading=90)
        self.chose_random_direction()
        self.step_count = 0

    def chose_random_direction(self):
        heading = random.uniform(0, 360)
        self.h = heading

    def read_nearest_sensor(self, maze):
        """
        Poor robot, it's sensors are noisy and pretty strange,
        it only can measure the distance to the nearest beacon(!)
        and is not very accurate at that too!
        """
        return add_little_noise(super(Robot, self).read_nearest_sensor(maze))[0]
    
    def read_sensors(self, maze):
        """
        Returns the distances to all the sensors (beacons) in the same order as
        the way sensors are stored (maze.beacons). 
        -------------
        random_loss: True/False
            Simulate the randomized reading loss for some of the sensors (beacons)
        """
        return add_little_noise(super(Robot, self).read_sensors(maze))

    def move(self, maze, speed, delta_t):
        """
        Move the robot. Note that the movement is stochastic too.
        """
        self.step_count += 1
        self.advance_by(self.speed, delta_t=1, noisy=True, checker=None)
        # while True:
            # if self.advance_by(self.speed, delta_t=1, noisy=True,checker=lambda r, dx, dy: maze.is_free(r.x+dx, r.y+dy)):
            #     break
            # Bumped into something or too long in same direction,
            # chose random new direction
            # self.chose_random_direction()

# ------------------------------------------------------------------------
if __name__ == "__main__":
    RANDOM_LOSS = False
    world = Maze(maze_data, anc_list=anchor_list)

    # initial distribution assigns each particle an equal probability
    particles = Particle.create_random_particles(PARTICLE_COUNT, world)
    robbie = Robot(world)
    
    while True:
        # Read robbie's sensor
        # Only one raning result from one anchor is used. 
        # To expand the dimensions, use multiple anchors, then we have multiple readings
        # for particles and adjust particle weights accordingly. 
        # Update particle weight according to how good every particle matches
        # robbie's sensor reading
        # r_d = robbie.read_nearest_sensor(world)
        # for p in particles:
        #     if world.is_free(*p.xy):
        #         p_d = p.read_nearest_sensor(world)
        #         p.w = w_gauss(r_d, p_d)
        #     else:
        #         p.w = 0
        # time.sleep(0.5)
        all_x, all_y = [p.x for p in particles], [p.y for p in particles]
        if not RANDOM_LOSS:
            r_ds = robbie.read_sensors(world)
            for p in particles:
                if world.is_free(*p.xy):
                    p_ds = p.read_sensors(world)
                    p.w = w_gauss_multi(r_ds, p_ds)
                else:
                    p.w = 0
            chosen_idx = [range(len(r_ds))]
        else:
            r_ds = robbie.read_sensors(world)
            chosen_idx = random.sample(range(len(r_ds)), random.randint(0, len(r_ds)))
            for i in chosen_idx:
                r_ds[i] = float('inf')
            for p in particles:
                if world.is_free(*p.xy):
                    p_ds = p.read_sensors(world)
                    for i in chosen_idx:
                        p_ds[i] = float('inf')
                    new_weight = w_gauss_multi(r_ds, p_ds)
                    if new_weight:
                        p.w = new_weight
                else:
                    p.w = 0

        # ---------- Try to find current best estimate for display ----------
        m_x, m_y, m_confident = compute_mean_point(world, particles)

        # ---------- Show current state ----------
        world.draw(chosen_idx)
        world.show_particles(particles)
        world.show_mean(m_x, m_y, m_confident)
        world.show_robot(robbie)
        # ---------- Shuffle particles ----------
        new_particles = []

        # Normalise weights
        nu = sum(p.w for p in particles)
        if nu:
            for p in particles:
                p.w = p.w / nu

        # create a weighted distribution, for fast picking
        dist = WeightedDistribution(particles)

        for _ in particles:
            p = dist.pick()
            if p is None:  # No pick b/c all totally improbable
                new_particle = Particle.create_random_particles(1, world)[0]
            else:
                new_particle = Particle(p.x, p.y,
                        heading=robbie.h if ROBOT_HAS_COMPASS else p.h,
                        noisy=True)
            new_particles.append(new_particle)

        particles = new_particles

        # ---------- Move things ----------
        old_heading = robbie.h
        robbie.move(world)
        d_h = robbie.h - old_heading

        # Move particles according to my belief of movement (this may
        # be different than the real movement, but it's all I got)
        for p in particles:
            p.h += d_h # in case robot changed heading, swirl particle heading too
            p.advance_by(robbie.speed)
