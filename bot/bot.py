""" 
This bot is a bot from episode 2 of Bits of Code(https://bit.ly/3TjclBh). 
It is a simple bot that expands to gold bases and builds zealots trying to reach Max supply before 5:46 in game time. 
use the map Prion Terrace. 

Download the map from the following link: https://bit.ly/3UUr1bk

The results will vary based on several variables:

- Recall : at 2:40 the bot recalls to the 3rd, the amount needs to be 8 probes, more or less will skew results
- When building gateways there is a chance the probe will get stuck
- The 5th nexus won't get built as a result of the recall being off

Current Performance: 5:45

"""
import random
import math

from typing import Dict, Set
from loguru import logger

from itertools import chain


from sc2.bot_ai import BotAI, Race
from sc2.data import Result
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.buff_id import BuffId
from sc2.position import Point2, Point3
from sc2.unit import Unit
from sc2.units import Units
from sc2 import position
from sc2.constants import UnitTypeId, AbilityId, UpgradeId, BuffId

from bot.speedmining import get_speedmining_positions
from bot.speedmining import split_workers
from bot.speedmining import mine

from scipy.optimize import OptimizeResult, differential_evolution



class DragonBot(BotAI):
    NAME: str = "DragonBot"
    """This bot's name"""
    #keep track of the last expansion index
    def __init__(self):
        super().__init__()
        self.last_expansion_index = -1
        
        self.warpgate_positions = {}                 # dictionary to keep track of the positions around a Pylon where we can warp in units
        self.townhall_saturations = {}               # lists the mineral saturation of townhalls in queues of 40 frames, we consider the townhall saturated if max_number + 1 >= ideal_number
        self.assimilator_age = {}                    # this is here to tackle an issue with assimilator having 0 workers on them when finished, although the building worker is assigned to it
        self.workers_building = {}                   # dictionary to keep track of workers building a building
        self.expansion_probes = {}                   # dictionary to keep track probes expanding
        self.unit_roles = {}                         # dictionary to keep track of the roles of the units
        self.built_positions = set()                 # Keep track of positions where a Gateway has been built
        self.pylons = []                             # List to keep track of Pylons
        self.probe = None
        self.occupied_positions = []
        self.probe_moved = False                    # Flag to indicate if the probe has been ordered to move

        self.gateway_queue = []                      # Queue to keep track of the order of building Gateways
        self.warpgate_list = []
        
        self.last_two_warpgates = []
        self.worker_transfer_delay = 0

      

    # Put this inside your bot AI class
    def _draw_debug_sphere_at_point(self, point: Point2):
        height = self.get_terrain_z_height(point)  # get the height in world coordinates
        radius = 1                                 # set the radius of the sphere
        point3 = Point3((point.x, point.y, height))  # convert the 2D point to a 3D point
        self._client.debug_sphere_out(point3, radius, color=Point3((255, 0, 0)))

    RACE: Race = Race.Protoss
    """This bot's Starcraft 2 race.
    Options are:
        Race.Terran
        Race.Zerg
        Race.Protoss
        Race.Random
    """
    
    async def on_start(self):
        """
        This code runs once at the start of the game
        Do things here before the game starts
        """
        

        print("Game started")
        self.client.game_step = 2    
        self.speedmining_positions = get_speedmining_positions(self)
        split_workers(self)   
        
        
        self.nexus_creation_times = {nexus.tag: self.time for nexus in self.townhalls.ready}  # tracks the creation time of Nexus
        self.built_cybernetics_core = False # Flag to indicate if the Cybernetics Core has been built
        


        # Positions for Key Buildings
        self.positions = {
            Point2((108 + 1, 24)): None,
            Point2((105 + 1, 24)): None,
            Point2((111 + 1, 27)): None,
            Point2((108 + 1, 27)): None,
            Point2((105 + 1, 27)): None,
            Point2((102 + 1, 27)): None,
            Point2((102 + 1, 30)): None,
            Point2((105 + 1, 30)): None,
            Point2((110 + 1, 30)): None,
            Point2((113 + 1, 30)): None,      
            Point2((112 + 1, 33)): None,
            Point2((109 + 1, 33)): None,
            Point2((106 + 1, 33)): None,
            Point2((103 + 1, 33)): None,
        }           
    
    
    #Create a list of  all gold starting locations
    def _find_gold_expansions(self) -> list[Point2]:
            gold_mfs: list[Unit] = [
                mf for mf in self.mineral_field
                if mf.type_id in {UnitTypeId.RICHMINERALFIELD, UnitTypeId.RICHMINERALFIELD750}
            ]

            gold_expansions: list[Point2] = []

            # check if gold_mfs are on the map
            if len(gold_mfs) > 0:     
                for expansion in self.expansion_locations_list:
                    for gold_mf in gold_mfs:
                        if gold_mf.position.distance_to(expansion) < 12.5:
                            gold_expansions.append(expansion)
                            break
            # sort gold_expansions by proximity to the bot's starting location
            gold_expansions.sort(key=lambda x: x.distance_to(self.start_location))
            gold_expansions.insert(1, gold_expansions.pop(2))

            return gold_expansions        
    
    async def on_building_construction_complete(self, building):
        if building.type_id == UnitTypeId.NEXUS:
            self.nexus_creation_times[building.tag] = self.time  # update the creation time when a Nexus is created
        if building.type_id == UnitTypeId.GATEWAY:
            self.gateway_queue.append(building.tag)  # Add the Gateway to the queue
        if building.type_id == UnitTypeId.PYLON:
            self.pylons.append(building)  # Add Pylon to list when it's created
        

    
    
    async def warp_new_units(self, pylon):
        pylon = self.pylons[1]
        # Create a 6x6 grid of positions around the Pylon
        positions = [pylon.position.to2.offset((x, y)) for x in range(-3, 4) for y in range(-3, 4)]
        positions = [pos for pos in positions if pos not in self.occupied_positions]  # Exclude already occupied positions

        random.shuffle(positions)  # Randomize the order of the positions

        # Warp in Zealots from Warpgates near a Pylon if below supply cap
        for i, warpgate in enumerate(self.structures(UnitTypeId.WARPGATE)):
            abilities = await self.get_available_abilities(warpgate)
            if self.can_afford(UnitTypeId.ZEALOT) and AbilityId.WARPGATETRAIN_ZEALOT in abilities:
                position = positions.pop(0) if positions else None  # Take the first available position, or None if all positions are occupied
                placement = await self.find_placement(AbilityId.WARPGATETRAIN_ZEALOT, position, placement_step=1, max_distance=10)
                if placement is None:
                    print(f"Can't find placement location for {position}")
                    continue
                self.occupied_positions.append(placement)  # Add the placement to the list of occupied positions
                self._draw_debug_sphere_at_point(Point3((position.x, position.y, pylon.position3d.z)))  # Draw a debug sphere at the placement location

                try:
                    warpgate.warp_in(UnitTypeId.ZEALOT, placement)  # Warp in the Zealot at the found placement
                except Exception as e:
                    print(f"Failed to warp in Zealot at {placement}: {e}")  # Log any exceptions that occur during warp-in  
    
    def find_aoe_position(
        self,
        effect_radius: float,
        targets: Units,
    ) -> Point2:
        """

        @param effect_radius: radius of the effect we're trying to place
        @param targets: the units we're trying to hit with the effect
        @return Point2: where to place the effect
        """
        if len(targets) == 0:
            return None
        elif len(targets) == 1:
            return targets.first.position

        # Sort the targets by their distance to the center of your base
        targets = sorted(targets, key=lambda unit: unit.distance_to(self.start_location))

        # Select the closest 8 units
        targets = targets[:6] # this doesn't work accurately, but it's good enough for now

        x_min, x_max, y_min, y_max = self.get_bounding_box(targets)
        boundaries = ((x_min, x_max), (y_min, y_max))

        def f(params: tuple[float, float]) -> float:
            """Function for optimization."""
            # the (x, y) coordinate being checked
            x, y = params
            # we're going to store the hits here- this is what we optimize
            all_evals: list[float] = []
            hits = 0  # Counter for the number of hits
            for unit in targets:
                i, j = unit.position
                # this is needed for adjusting what's considered a "hit"
                y_offset: float = math.log(1 + effect_radius + unit.radius)
                # the full equation is complicated so it's split up for legibility
                dist: float = math.sqrt(((x - i) ** 2 + (y - j) ** 2))
                exponent: float = 100 * (math.log(dist + 1) - y_offset)
                denominator: float = 1 + math.e ** exponent
                fraction: float = 2 / denominator
                # if the value is positive, the effect missed. If the value is negative, it hit. Since we want to
                # maximize the hits, it's important that misses don't affect how good a particular position is.
                append_value = (
                        min([-1 * (fraction - 1), 0]) * 1
                )
                all_evals.append(append_value)
                if append_value < 0:  # If the effect hit the unit
                    hits += 1

            # Prioritize positions that hit exactly 8 units
            if hits == 8:
                return float('inf')  # High value for 8 hits
            elif hits > 8:
                return float('-inf')  # Low value for more than 8 hits
            else:
                return sum(all_evals)  # Lower value for less than 8 hits

        result: OptimizeResult = differential_evolution(f, bounds=boundaries, tol=1e-10)
        return Point2(result.x)
    
    # noinspection PyMethodMayBeStatic
    def get_bounding_box(self, units: Units) -> tuple[float, float, float, float]:
        """
        Given some units, form a rectangle around them.
        Returns minimum x, maximum x, minimum y, maximum y
        """
        x_coords: list[float] = []
        y_coords: list[float] = []
        for unit in units:
            x_coords.append(unit.position.x)
            y_coords.append(unit.position.y)
        return min(x_coords), max(x_coords), min(y_coords), max(y_coords)
        
    
    def get_unit(self, tag):
        return self.units.find_by_tag(tag)

    async def on_step(self, iteration: int):
        """
        This code runs continually throughout the game
        """
        target_base_count = 6    # Number of total bases to expand to before stoping
        expansion_loctions_list = self._find_gold_expansions()   # Define expansion locations

        nexus = self.townhalls.ready.random
        closest = self.start_location
        self.resource_by_tag = {unit.tag: unit for unit in chain(self.mineral_field, self.gas_buildings)}


        for point in self.positions:
            self._draw_debug_sphere_at_point(point)

        

        
        
                          
        
        # After 13 warpgates, build an explosion of pylons until we are at 14
        if self.structures(UnitTypeId.GATEWAY).amount + self.structures(UnitTypeId.WARPGATE).amount >= 13:
            direction = Point2((-4, -1))
            # Retrieve the current state of the probe using its tag
            expand_probe_tags = [tag for tag, role in self.unit_roles.items() if role == "expand"]
            if expand_probe_tags:
                for tag in expand_probe_tags:
                    self.probe = self.units.find_by_tag(tag)
                    if self.probe and not self.probe.orders:  # Check if the probe exists and is not currently executing an order
                        if self.time >= 4 * 60 + 35  and self.structures(UnitTypeId.PYLON).amount < 2 and self.already_pending(UnitTypeId.PYLON) < 1:
                            direction = Point2((-6, -2))
                            if self.can_afford(UnitTypeId.PYLON):
                                west_most_gateway = min(self.structures(UnitTypeId.GATEWAY), key=lambda gateway: gateway.position.x,)
                                await self.build(UnitTypeId.PYLON, near=west_most_gateway.position + direction, build_worker=self.probe)
                        if self.structures(UnitTypeId.PYLON).amount >= 2 and self.structures(UnitTypeId.PYLON).amount < 5 and self.time > 4 * 60 + 38:
                            if self.can_afford(UnitTypeId.PYLON):
                                await self.build(UnitTypeId.PYLON, near=closest.position + direction * 5, build_worker=self.probe)
                        elif self.structures(UnitTypeId.PYLON).amount >= 5 and self.structures(UnitTypeId.PYLON).amount < 8 and self.time > 4 * 60 + 48:
                            if self.can_afford(UnitTypeId.PYLON):
                                await self.build(UnitTypeId.PYLON, near=closest.position + direction * 3, build_worker=self.probe)
                        elif self.structures(UnitTypeId.PYLON).amount >= 8 and self.structures(UnitTypeId.PYLON).amount < 10 and self.time > 4 * 60 + 52:
                            if self.can_afford(UnitTypeId.PYLON):
                                await self.build(UnitTypeId.PYLON, near=closest.position + direction * 3, build_worker=self.probe)
                        elif self.structures(UnitTypeId.PYLON).amount < 12 and self.time > 5 * 60 + 8:
                            if self.can_afford(UnitTypeId.PYLON):
                                await self.build(UnitTypeId.PYLON, near=closest.position + direction * 1, build_worker=self.probe)
                        elif self.structures(UnitTypeId.PYLON).amount < 14 and self.time > 5 * 60 + 23:
                            if self.can_afford(UnitTypeId.PYLON):
                                await self.build(UnitTypeId.PYLON, near=closest.position + direction * 2, build_worker=self.probe)
                      
        
        
        mine(self, iteration)
                    
        
            

        ## expansion logic: 
        # if we have less than target base count and build 5 nexuses, 4 at gold bases and then last one at the closest locations all with the same probe aslong as its not building an expansion 
        if self.townhalls.amount < target_base_count:
                
            if self.last_expansion_index < 2 and self.townhalls.amount < target_base_count and self.time < 2 * 60 + 30: 
                if self.can_afford(UnitTypeId.NEXUS):   
                    self.last_expansion_index += 1
                    if self.last_expansion_index == 1:
                        self.worker_transfer_delay = self.time + 79  # Nexus build time + mass recall duration
                    next_location = expansion_loctions_list[self.last_expansion_index + 1]
                    location = expansion_loctions_list[self.last_expansion_index]
                    self.probe.build(UnitTypeId.NEXUS, location)
                    print(self.time_formatted, "expanding to gold base:", self.last_expansion_index)
                    
                    if self.last_expansion_index < 2:
                        self.probe.move(next_location, queue=True)
                    else:
                        self.probe.gather(self.mineral_field.closest_to(location), queue=True)
                        self.probe.return_resource(queue=True)
                    
            
            elif self.last_expansion_index < 3 and self.time > 2 * 60 + 19 and self.time < 2 * 60 + 45:
                if self.last_expansion_index  < 3 and not self.probe_moved:
                    location: Point2 = expansion_loctions_list[3]
                    self.probe.move(location)
                    self.probe_moved = True  # Set the flag to True when the probe is ordered to move
                if self.can_afford(UnitTypeId.NEXUS):
                    self.last_expansion_index += 1
                    next_location = expansion_loctions_list[self.last_expansion_index + 1]
                    location = expansion_loctions_list[self.last_expansion_index]
                    self.probe.build(UnitTypeId.NEXUS, location)
                    print(self.time_formatted, "expanding to gold base:", self.last_expansion_index)
                    self.probe.gather(self.mineral_field.closest_to(location), queue=True)
                    self.probe.return_resource(queue=True)
                    self.probe_moved = False # Reset the flag when the probe is ordered to move

            elif self.last_expansion_index == 3 and self.townhalls.amount < target_base_count:
                if not self.probe_moved and self.time > 3 * 60 + 7:
                        location: Point2 = await self.get_next_expansion()
                        self.probe.move(location)
                        self.probe_moved = True  # Set the flag to True when the probe is ordered to move
                if self.can_afford(UnitTypeId.NEXUS) and self.built_cybernetics_core == True:
                    location: Point2 = await self.get_next_expansion()
                    self.probe.build(UnitTypeId.NEXUS, location)
                    print(self.time_formatted, "expanding to last expansion")
                    self.last_expansion_index += 1
                    if self.last_expansion_index == 4:
                        self.probe.move(self.start_location.towards(self.game_info.map_center, 10), queue=True)

        
        
        ### Key Buildings
        if self.structures(UnitTypeId.PYLON).ready:
            pylon = self.structures(UnitTypeId.PYLON).ready.first
            # Filter workers that are not assigned to gather vespene gas
            non_gas_workers = [worker for worker in self.workers if worker.order_target is None or worker.order_target not in self.vespene_geyser and not worker.is_carrying_vespene]
            if non_gas_workers:
                # Select the worker that is closest to the pylon
                probe2 = min(non_gas_workers, key=lambda worker: worker.distance_to(pylon))
            for pos in self.positions.keys():
                if pos in self.built_positions:  # Skip positions where a Gateway has already been built
                    continue
                if self.townhalls.amount >= 4 and self.structures(UnitTypeId.GATEWAY).amount + self.structures(UnitTypeId.WARPGATE).amount < 1 and self.already_pending(UnitTypeId.GATEWAY) == 0:
                    if self.can_afford(UnitTypeId.GATEWAY):
                        probe2.return_resource()
                        probe2.build(UnitTypeId.GATEWAY, pos)
                        self.positions[pos] = UnitTypeId.GATEWAY
                        self.built_positions.add(pos)  # Remember this position
                        print(f"Building 1st Gateway at {self.time_formatted}")

                elif not self.structures(UnitTypeId.WARPGATE) and self.structures(UnitTypeId.GATEWAY).amount < 5 and self.townhalls.amount == 6 and self.structures(UnitTypeId.CYBERNETICSCORE) and self.time > 3 * 60 + 34:
                    if self.can_afford(UnitTypeId.GATEWAY):
                        probe2.build(UnitTypeId.GATEWAY, pos, queue=True)
                        self.positions[pos] = UnitTypeId.GATEWAY
                        self.built_positions.add(pos)  # Remember this position
                        print(f" Next Gateways built at {self.time_formatted}")  # Print the current game time
                elif not self.structures(UnitTypeId.WARPGATE) and self.structures(UnitTypeId.GATEWAY).amount < 13 and self.townhalls.amount == 6 and self.time > 4 * 60 + 3:
                    if self.can_afford(UnitTypeId.GATEWAY):
                        probe2.build(UnitTypeId.GATEWAY, pos, queue=True)
                        self.positions[pos] = UnitTypeId.GATEWAY
                        self.built_positions.add(pos)  # Remember this position
                        print(f" Next Gateways built at {self.time_formatted}")  # Print the current game time

                if not self.built_cybernetics_core and self.structures(UnitTypeId.CYBERNETICSCORE).amount < 1 and self.already_pending(UnitTypeId.CYBERNETICSCORE) == 0:
                    if self.can_afford(UnitTypeId.CYBERNETICSCORE) and self.structures(UnitTypeId.GATEWAY).ready:
                        self.built_cybernetics_core = True
                        probe2.return_resource()
                        probe2.build(UnitTypeId.CYBERNETICSCORE, pos)
                        self.positions[pos] = UnitTypeId.CYBERNETICSCORE
                        self.built_positions.add(pos)  # Remember this position
                        print(f"Building Cybernetics Core at {self.time_formatted}")
        
        # build 1 gas near the starting nexus
        if self.townhalls.amount >= 5:
            if self.structures(UnitTypeId.ASSIMILATOR).amount < 1 and not self.already_pending(UnitTypeId.ASSIMILATOR):
                if self.can_afford(UnitTypeId.ASSIMILATOR):
                    vgs = self.vespene_geyser.closer_than(15, closest)
                    if vgs:
                        worker = self.select_build_worker(vgs.first.position)
                        worker.build(UnitTypeId.ASSIMILATOR, vgs.first)
                        worker.gather(self.mineral_field.closest_to(vgs.first), queue=True)
                        print(f"Building Assimilator at {self.time_formatted}")
        
        
        ### Probe Control ###
        
        # Build first pylon if we are low on supply up until 4 bases after 4 bases build pylons until supply cap is 200
        if self.supply_left <= 2 and self.already_pending(UnitTypeId.PYLON) == 0 and self.structures(UnitTypeId.PYLON).amount < 1: 
            if self.can_afford(UnitTypeId.PYLON): 
                pylon_position = nexus.position.towards(self.game_info.map_center, 10)
                probe = self.workers.random
                probe.return_resource()
                probe.build(UnitTypeId.PYLON, pylon_position, queue=True)

           
        # Move the first probe to build the first nexus
        if 49 <= self.time < 50 and not any(role == "expand" for role in self.unit_roles.values()):
            self.probe = self.workers.random
            self.unit_roles[self.probe.tag] = "expand"
            self.probe.return_resource(queue=True)
            self.probe.move(expansion_loctions_list[0], queue=True)


           
        
        #Remove the probe from the expansion_probes and unit_roles dictionary if max pylons are built
        if self.supply_used < 200 and self.structures(UnitTypeId.PYLON).amount == 14:
            if self.probe.tag in self.expansion_probes:
                del self.expansion_probes[self.probe.tag]
            if self.probe.tag in self.unit_roles:
                del self.unit_roles[self.probe.tag]

        # Determine the maximum number of probes based on the number of bases
        if len(self.townhalls) < 3:
            max_probes = 21
        ###elif len(self.townhalls) < 4:
        ###    max_probes = 22
        elif not self.structures(UnitTypeId.ASSIMILATOR):
            max_probes = 31
        else:
            max_probes = 170

        # Train probes up to the maximum number for each Nexus
        if self.supply_workers + self.already_pending(UnitTypeId.PROBE) < max_probes:
            for nexus in self.townhalls.ready:  # Iterate over all Nexus buildings
                if self.supply_workers + self.already_pending(UnitTypeId.PROBE) <  self.townhalls.amount * 22:
                    if self.can_afford(UnitTypeId.PROBE):
                        # Check if the Nexus is idle or about to finish training its current probe
                        if (nexus.is_idle or (nexus.orders and nexus.orders[0].progress > 0.95)) and len(nexus.orders) <= 1:
                            nexus.train(UnitTypeId.PROBE)
                            
        # Research Warp Gate if Cybernetics Core is complete
        if self.structures(UnitTypeId.CYBERNETICSCORE).ready and self.can_afford(UpgradeId.WARPGATERESEARCH) and self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) == 0:
            ccore = self.structures(UnitTypeId.CYBERNETICSCORE).ready.first
            if ccore.is_idle:
                ccore.research(UpgradeId.WARPGATERESEARCH)
                print(self.time_formatted, " - researching warp gate - Supply: ", self.supply_used)
                        
        # Morph to warp gates when warp gate research is complete
        if self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) == 0 and self.structures(UnitTypeId.GATEWAY).ready:
            for gateway in self.structures(UnitTypeId.GATEWAY).ready.idle:
                gateway(AbilityId.MORPH_WARPGATE)

        # warp in zealots if warpgates is ready else build zealots
        if self.structures(UnitTypeId.WARPGATE).ready:
            await self.warp_new_units(pylon)
        elif not self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) == 1: 
            if self.time > 4 * 60 + 25 and self.time < 4 * 60 + 33 and self.structures(UnitTypeId.GATEWAY).amount == 13:
                for gateway in self.structures(UnitTypeId.GATEWAY).ready.idle:
                    if self.can_afford(UnitTypeId.ZEALOT):
                        gateway.train(UnitTypeId.ZEALOT)
                        
        # When a Gateway is transformed into a Warpgate, remove it from the queue and add it to the list
        if self.structures(UnitTypeId.WARPGATE).ready:
            for warpgate in self.structures(UnitTypeId.WARPGATE).ready:
                if warpgate.tag in self.gateway_queue:
                    self.gateway_queue.remove(warpgate.tag)
                    self.warpgate_list.append(warpgate.tag)

                    # Update last_two_warpgates every time a new warpgate is added
                    self.last_two_warpgates = self.warpgate_list[-2:] if len(self.warpgate_list) >= 2 else self.warpgate_list

        ## Nexus Abilities #
                    
        # Check if the time is between 5:25 and 5:28
        if 5 * 60 + 25 < self.time < 5 * 60 + 29:
            chronoboosts_used = 0
            for warpgate_tag in self.last_two_warpgates:
                if chronoboosts_used >= 2:
                    break
                warpgate = self.structures.ready.find_by_tag(warpgate_tag)
                if warpgate is not None and not warpgate.has_buff(BuffId.CHRONOBOOSTENERGYCOST):
                    abilities = await self.get_available_abilities(warpgate)
                    if AbilityId.WARPGATETRAIN_ZEALOT not in abilities:
                        chronoboost_applied = False
                        for nexus in self.townhalls.ready:
                            if nexus.energy >= 50:
                                nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, warpgate)
                                chronoboosts_used += 1
                                if warpgate.tag in self.last_two_warpgates:
                                    self.last_two_warpgates.remove(warpgate.tag)
                                chronoboost_applied = True
                            if chronoboost_applied:
                                break  # Skip the remaining Nexuses for the current Warpgate
                                

        # Check if the time is between 00:33 and 4:45
        elif 33 < self.time < 4 * 60 + 45:
            # Check if the time is between 4:14 and 4:40
            if self.townhalls.ready.amount == 3:
                nexus = self.townhalls.ready[2]
                if nexus.energy >= 50 and AbilityId.EFFECT_MASSRECALL_NEXUS in await self.get_available_abilities(nexus):
                    probes = self.units(UnitTypeId.PROBE).closer_than(10, self.start_location)
                    best_location = self.find_aoe_position(2.5, probes)  # 2.5 is the radius of the Mass Recall effect
                    if best_location is not None:
                        nexus(AbilityId.EFFECT_MASSRECALL_NEXUS, best_location)
                        print(self.time_formatted, " - mass recalling probes to 3rd nexus")
            elif 4 * 60 + 14 < self.time < 4 * 60 + 40:
                ccore = self.structures(UnitTypeId.CYBERNETICSCORE).ready.first
                if ccore and not ccore.has_buff(BuffId.CHRONOBOOSTENERGYCOST):
                    for nexus in self.townhalls.ready:
                        if nexus.energy >= 50:
                            nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, ccore)
            else:
                # Find the least saturated nexus that doesn't have the chronoboost buff and is not idle
                least_saturated_nexus = next((nexus for nexus in sorted(self.townhalls.ready, key=lambda n: n.assigned_harvesters) if not nexus.has_buff(BuffId.CHRONOBOOSTENERGYCOST) and nexus.is_idle == False), None)

                if least_saturated_nexus is not None:
                    # Find a Nexus with enough energy
                    nexus_with_energy = next((nexus for nexus in self.townhalls.ready if nexus.energy >= 50), None)

                    if nexus_with_energy is not None:
                        # Chronoboost the least saturated Nexus
                        nexus_with_energy(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, least_saturated_nexus)

        # After 5:30, it can just chronoboost itself if it has the energy
        elif self.time > 5 * 60 + 30:
            for nexus in self.townhalls.ready:
                if nexus.energy >= 50 and not nexus.has_buff(BuffId.CHRONOBOOSTENERGYCOST) and nexus.is_idle == False:
                    nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, nexus)


        #Benchmarks
        if self.time == 4 * 60 + 55:
            warpgate_status = "completed" if UpgradeId.WARPGATERESEARCH in self.state.upgrades else "not completed"
            print(self.supply_used, "supply used at 4:55 with", self.units(UnitTypeId.ZEALOT).amount, "zealots", "and", self.workers.amount, "probes. Warpgate is", warpgate_status)
    
        if self.time == 5 * 60 + 40:
            print(self.supply_used, "supply used at 5:39")

        # if we hit supply cap surrender if not move zealots to the center of the map
        zealots = self.units(UnitTypeId.ZEALOT)
        if self.supply_used == 200:
            print(self.time_formatted, "supply cap reached with:", self.structures(UnitTypeId.WARPGATE).ready.amount, "warpgates", "+", self.structures(UnitTypeId.PYLON).ready.amount, "pylons", "and", self.townhalls.amount, "nexuses", "+", self.units(UnitTypeId.ZEALOT).amount, "zealots", "and", self.workers.amount, "probes")
            await self.chat_send("Supply Cap Reached at:" + self.time_formatted)
            await self.client.leave()
        else:
            for zealot in zealots:
                zealot(AbilityId.ATTACK, self.game_info.map_center)
           
    
    async def on_end(self, result: Result):
        """
        This code runs once at the end of the game
        Do things here after the game ends
        """
        print("Game ended.")
