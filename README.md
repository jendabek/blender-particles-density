# Blender Particles Density
## A Blender 2.79 addon which adjusts the particles count to maintain the desired density.

Blender is a nice tool for planting objects (like vegetation) onto the terrain using Particle System + painting the density Vertex Group, but the need of adjusting the particles count constantly can become very confusing and time-consuming - the addon should solve this workflow limitation.

## Original Behavior
Normally, you set the total *Emmission Number*.<br/>
As this is the constant number, the density gets lower as you Weight Paint more area (and vice-versa):
![](readme-files/standard.gif)


# Addon Behavior
With the addon, you set the *Density* parameter instead, and the count is automatically adjusted:
![](readme-files/addon.gif)
