""" 
This bot is a bot from episode 2 of Bits of Code(https://bit.ly/3TjclBh). 
It is a simple bot that expands to gold bases and builds zealots trying to reach Max supply by 5:46 in game time. 
use the map Prion Terrace. 

Download the map from the following link: https://bit.ly/3UUr1bk
"""
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
from sc2.constants import UnitTypeId


from bot.speedmining import get_speedmining_positions
from bot.speedmining import split_workers
from bot.speedmining import mine



class DragonBot(BotAI):
    NAME: str = "DragonBot"
    """This bot's name"""
    #keep track of the last expansion index
    def __init__(self):
        super().__init__()
        self.last_expansion_index = -1
        
        self.townhall_saturations = {}               # lists the mineral saturation of townhalls in queues of 40 frames, we consider the townhall saturated if max_number + 1 >= ideal_number
        self.assimilator_age = {}                    # this is here to tackle an issue with assimilator having 0 workers on them when finished, although the building worker is assigned to it
        self.workers_building = {}                   # dictionary to keep track of workers building a building
        self.expansion_probes = {}                   # dictionary to keep track probes expanding
        self.unit_roles = {}                         # dictionary to keep track of the roles of the units
        self.built_positions = set()                 # Keep track of positions where a Gateway has been built
        self.pylons = []                             # List to keep track of Pylons
        self.probe = None

    
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
        

        
        # Select a probe and assign the role of "expand"
        self.probe = self.workers.random
        self.unit_roles[self.probe.tag] = "expand"
        self.expansion_probes[self.probe.tag] = self.probe.position
        self.built_cybernetics_core = False

        # Check if the positions dictionary is already created
        
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

            return gold_expansions        
    
    async def on_building_construction_complete(self, building):
        if building.type_id == UnitTypeId.PYLON:
            self.pylons.append(building)  # Add Pylon to list when it's created

    
    async def warp_new_units(self, pylon):
        if pylon not in self.pylons or self.pylons.index(pylon) != 1:  # Only warp in at the second Pylon
            return
        #warp in zealots from warpgates near a pylon if below supply cap
        for warpgate in self.structures(UnitTypeId.WARPGATE).ready.idle:
            abililities = await self.get_available_abilities(warpgate)
            if self.can_afford(UnitTypeId.ZEALOT) and AbilityId.WARPGATETRAIN_ZEALOT in abililities and self.supply_used < 200:
                direction = pylon.position.towards(self.game_info.map_center, 1)
                positions = [pylon.position.to2.offset((x, y)).towards(direction, 5) for x in range(-6, 7) for y in range(0, 5)]  # Create a grid of positions in front of the Pylon
                for position in positions:
                    placement = await self.find_placement(AbilityId.WARPGATETRAIN_ZEALOT, position, placement_step=1)
                    if placement is not None:
                        warpgate.warp_in(UnitTypeId.ZEALOT, placement)
                        # Removed the break statement
    
    
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

        # Build first pylon if we are low on supply up until 4 bases after 4 bases build pylons until supply cap is 200
        if self.supply_left <= 2 and self.already_pending(UnitTypeId.PYLON) == 0 and self.structures(UnitTypeId.PYLON).amount < 1: 
            if self.can_afford(UnitTypeId.PYLON): 
                pylon_position = nexus.position.towards(self.game_info.map_center, 10)
                self.probe.build(UnitTypeId.PYLON, pylon_position)
                print(f"Pylon position: {pylon_position}")
                self.probe.move(expansion_loctions_list[0], queue=True)       
        
        # After 13 warpgates, build an explosion of pylons until we are at 14
        elif self.structures(UnitTypeId.GATEWAY).amount + self.structures(UnitTypeId.WARPGATE).amount >= 13:
            direction = Point2((-4, 0))
            if self.time >= 4 * 60 + 25  and self.structures(UnitTypeId.PYLON).amount < 2 and self.already_pending(UnitTypeId.PYLON) < 1:
                direction = Point2((-5, 0))
                if self.can_afford(UnitTypeId.PYLON):
                    # Find the west most Gateway
                    west_most_gateway = min(self.structures(UnitTypeId.GATEWAY), key=lambda gateway: gateway.position.x)
                    # Build the Pylon slightly to the left of the west most Gateway
                    await self.build(UnitTypeId.PYLON, near=west_most_gateway.position + direction, build_worker=self.probe)
            if self.structures(UnitTypeId.PYLON).amount < 5  and self.supply_used >= 76:
                if self.can_afford(UnitTypeId.PYLON):
                    await self.build(UnitTypeId.PYLON, near=closest.position + direction * 4, build_worker=self.probe)
            if self.structures(UnitTypeId.PYLON).amount  < 10  and self.supply_used >= 88:
                if self.can_afford(UnitTypeId.PYLON):
                    await self.build(UnitTypeId.PYLON, near=closest.position + direction * 3, build_worker=self.probe)
            if self.structures(UnitTypeId.PYLON).amount < 12 and self.supply_used >= 122:
                if self.can_afford(UnitTypeId.PYLON):
                    await self.build(UnitTypeId.PYLON, near=closest.position + direction * 2, build_worker=self.probe)
            if self.structures(UnitTypeId.PYLON).amount < 14  and self.supply_used >= 150:
                if self.can_afford(UnitTypeId.PYLON):
                    await self.build(UnitTypeId.PYLON, near=closest.position + direction * 2, build_worker=self.probe)

        
        
        
        mine(self, iteration)
                    
        #Building Probes to reach 200 supply fast
        if self.supply_used < 200 and self.structures(UnitTypeId.PYLON).amount == 14:
            if self.probe.tag in self.expansion_probes:
                del self.expansion_probes[self.probe.tag]
            if self.probe.tag in self.unit_roles:
                del self.unit_roles[self.probe.tag]
            """for nexus in self.townhalls.ready:
                if self.can_afford(UnitTypeId.PROBE) and nexus.is_idle:
                    nexus.train(UnitTypeId.PROBE)"""

        # expansion logic: if we have less than target base count and build 5 nexuses, 4 at gold bases and then last one at the closest locations all with the same probe aslong as its not building an expansion 
        if self.townhalls.amount < target_base_count:
                
            if self.last_expansion_index < 3 and self.townhalls.amount < target_base_count: 
                if self.can_afford(UnitTypeId.NEXUS): 
                    self.last_expansion_index += 1
                    next_location = expansion_loctions_list[self.last_expansion_index + 1]
                    location = expansion_loctions_list[self.last_expansion_index]
                    self.probe.build(UnitTypeId.NEXUS, location)
                    if self.last_expansion_index < 3:
                        print(self.time_formatted, "expanding to gold bases", self.last_expansion_index, "of", len(expansion_loctions_list), "total current bases=", self.townhalls.amount)
                        self.probe.move(next_location, queue=True)
                    else:
                        location: Point2 = await self.get_next_expansion()
                        self.probe.move(location)
                    
            elif self.last_expansion_index == 3 and self.townhalls.amount < target_base_count:
                if self.can_afford(UnitTypeId.NEXUS) and self.built_cybernetics_core == True:
                    location: Point2 = await self.get_next_expansion()
                    self.probe.build(UnitTypeId.NEXUS, location)
                    print(self.time_formatted, "expanding to last expansion")
                    self.probe.move(self.start_location.towards(self.game_info.map_center, 10))

         
        
        # key buildings, build 1 cybernetics core and 13 gateways
        if self.structures(UnitTypeId.PYLON).ready:
            pylon = self.structures(UnitTypeId.PYLON).ready.first
            probe2 = self.workers.closest_to(pylon)
            # iterate over the positions dictionary and build the structures
            for pos in self.positions.keys():
                if pos in self.built_positions:  # Skip positions where a Gateway has already been built
                    continue
                if self.townhalls.amount >= 4 and self.structures(UnitTypeId.GATEWAY).amount + self.structures(UnitTypeId.WARPGATE).amount < 1 and self.already_pending(UnitTypeId.GATEWAY) == 0:
                    if self.can_afford(UnitTypeId.GATEWAY):
                        probe2.build(UnitTypeId.GATEWAY, pos)
                        self.positions[pos] = UnitTypeId.GATEWAY
                        self.built_positions.add(pos)  # Remember this position
                        print(f"Building 1st Gateway at {self.time_formatted}")
                elif not self.structures(UnitTypeId.WARPGATE) and self.structures(UnitTypeId.GATEWAY).amount < 13 and self.townhalls.amount == 6 and self.structures(UnitTypeId.CYBERNETICSCORE):
                    if self.can_afford(UnitTypeId.GATEWAY):
                        probe2.build(UnitTypeId.GATEWAY, pos, queue=True)
                        self.positions[pos] = UnitTypeId.GATEWAY
                        self.built_positions.add(pos)  # Remember this position
                if not self.built_cybernetics_core and self.structures(UnitTypeId.CYBERNETICSCORE).amount < 1 and self.already_pending(UnitTypeId.CYBERNETICSCORE) == 0:
                    if self.can_afford(UnitTypeId.CYBERNETICSCORE) and self.structures(UnitTypeId.GATEWAY).ready:
                        self.built_cybernetics_core = True
                        probe2.build(UnitTypeId.CYBERNETICSCORE, pos)
                        self.positions[pos] = UnitTypeId.CYBERNETICSCORE
                        self.built_positions.add(pos)  # Remember this position
                        print(f"Building Cybernetics Core at {self.time_formatted}")
        
        # build 1 gas near the starting nexus
        if self.townhalls.amount >= 5:
            if self.structures(UnitTypeId.ASSIMILATOR).amount + self.already_pending(UnitTypeId.ASSIMILATOR) < 1:
                if self.can_afford(UnitTypeId.ASSIMILATOR):
                    vgs = self.vespene_geyser.closer_than(15, closest)
                    if vgs:
                        worker = self.select_build_worker(vgs.first.position)
                        if worker is None:
                            return
                        worker.build(UnitTypeId.ASSIMILATOR, vgs.first)
        
        # train probes = 22 per nexus
        if self.supply_workers + self.already_pending(UnitTypeId.PROBE) <  self.townhalls.amount * 22 and nexus.is_idle:
            if self.can_afford(UnitTypeId.PROBE):
                nexus.train(UnitTypeId.PROBE)

        # Research Warp Gate if Cybernetics Core is complete
        if self.structures(UnitTypeId.CYBERNETICSCORE).ready and self.can_afford(UpgradeId.WARPGATERESEARCH) and self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) == 0:
            ccore = self.structures(UnitTypeId.CYBERNETICSCORE).ready.first
            if ccore.is_idle:
                ccore.research(UpgradeId.WARPGATERESEARCH)
                print(self.time_formatted, " - researching warp gate")
                        
        # Morph to warp gates when warp gate research is complete
        if self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) == 0 and self.structures(UnitTypeId.GATEWAY).ready:
            for gateway in self.structures(UnitTypeId.GATEWAY).ready.idle:
                gateway(AbilityId.MORPH_WARPGATE)

        # warp in zealots if warpgates is ready else build zealots
        if self.structures(UnitTypeId.WARPGATE).ready:
            await self.warp_new_units(pylon)
        elif not self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) == 1: 
            if self.time > 4 * 60 + 19 and self.time < 4 * 60 + 24 and self.structures(UnitTypeId.GATEWAY).amount == 13:
                for gateway in self.structures(UnitTypeId.GATEWAY).ready.idle:
                    if self.can_afford(UnitTypeId.ZEALOT):
                        gateway.train(UnitTypeId.ZEALOT)
                        

        # Chrono boost nexus if cybernetics core is not idle and warpgates WARPGATETRAIN_ZEALOT is not available and mass recall probes to the 3rd nexus        
        if self.structures(UnitTypeId.WARPGATE).amount + self.structures(UnitTypeId.GATEWAY).amount == 13 and self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH)  == 1:
            warpgates = self.structures(UnitTypeId.WARPGATE).ready
            for warpgate in warpgates:
                abilities = await self.get_available_abilities(warpgate)
                if not AbilityId.WARPGATETRAIN_ZEALOT in abilities:
                    if not warpgate.has_buff(BuffId.CHRONOBOOSTENERGYCOST):
                        for nexus in self.townhalls.ready:
                            if nexus.energy >= 50:
                                nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, warpgate)
                                
        elif self.structures(UnitTypeId.CYBERNETICSCORE).ready and self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) != 1:
            ccore = self.structures(UnitTypeId.CYBERNETICSCORE).ready.first
            if not ccore.has_buff(BuffId.CHRONOBOOSTENERGYCOST) and self.time <= 4 * 60 + 40:
                for nexus in self.townhalls.ready:
                    if nexus.energy >= 50:
                        nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, ccore)
                         
        elif self.townhalls.ready.amount == 3:
            nexus = self.townhalls.ready[2]
            if nexus.energy >= 50 and AbilityId.EFFECT_MASSRECALL_NEXUS in await self.get_available_abilities(nexus):
                vespene_geyser = self.vespene_geyser.closest_to(self.start_location)
                mineral_patch = self.mineral_field.closest_to(vespene_geyser)
                midpoint = Point2(((mineral_patch.position.x + self.start_location.x) / 2, (mineral_patch.position.y + self.start_location.y) / 2))
                nexus(AbilityId.EFFECT_MASSRECALL_NEXUS, midpoint)
        
        elif self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) == 1:
            for nexus in self.townhalls.ready:
                if not nexus.has_buff(BuffId.CHRONOBOOSTENERGYCOST) and not nexus.is_idle:
                    if nexus.energy >= 50:
                        nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, nexus)
                        
        
        else:
            for nexus in self.townhalls.ready:
                if not nexus.has_buff(BuffId.CHRONOBOOSTENERGYCOST) and not nexus.is_idle:
                    if nexus.energy >= 50 and self.time > 17:
                        nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, nexus)
                        
        
        if self.time == 4 * 60 + 55:
            print(self.supply_used, "supply used at 4:55")
    
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
                zealot(AbilityId.ATTACK, nexus.position.towards(self.game_info.map_center, 5))

           
    
    async def on_end(self, result: Result):
        """
        This code runs once at the end of the game
        Do things here after the game ends
        """
        print("Game ended.")
