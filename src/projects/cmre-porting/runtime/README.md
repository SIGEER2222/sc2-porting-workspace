# CMRE Dynamic Observer

This layer is intentionally backend-neutral at the map boundary. It publishes normalized runtime
events through the externally owned `LibEFA54406` protocol and does not copy the Neuro repository.

`LibPortingObserver` owns reusable player-operation events and a minimal generic action surface.
Map-specific state remains in adapters such as `adapters/dead-of-night`.

The runtime launcher injects these files only into an isolated live test copy. The CMRE source
package and generated extraction stay unchanged.
