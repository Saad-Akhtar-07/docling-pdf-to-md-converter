"""Builds a 40-slide synthetic lecture deck for exercising
packages/planbuilder end to end (scripts/build_plan_demo.py).

No real lecture deck is checked into this repo (see generate_decks.py's own
docstring), and the extraction-regression fixture decks are 2-4 pages each
-- too small to meaningfully judge segmentation into 6-15 units. This is a
separate, standalone generator (not touching tests/fixtures/generate_decks.py,
which belongs to the extraction module's regression suite) producing one
topically coherent "Computer Networks" deck: 11 natural thematic groups
across 40 slides, each with real conceptual sentences so an LLM segmenter
and objective generator have something substantive to work with.

Deliberately lives under tests/fixtures/planbuilder_decks/, NOT
tests/fixtures/decks/ -- the latter is glob-discovered by
test_extraction_regression.py (every subdirectory there is expected to have
a matching golden expected_blocks.json), and this deck was never meant to
join that golden corpus.

Run directly to (re)generate the PDF:
    .venv\\Scripts\\python.exe tests\\fixtures\\generate_planbuilder_deck.py
"""

from pathlib import Path

import pymupdf

DECK_PATH = Path(__file__).parent / "planbuilder_decks" / "networking_101" / "deck.pdf"

PAGE_WIDTH = 720
PAGE_HEIGHT = 540

# (title, [sentences]) per slide, in final slide order. Grouped into 11
# thematic units purely for readability here -- the deck itself has no
# notion of units; that's exactly what packages/planbuilder must recover.
SLIDES: list[tuple[str, list[str]]] = [
    # Unit: Introduction to Computer Networks
    ("What Is a Computer Network?", [
        "A computer network connects independent computing devices so they can exchange data.",
        "Networks let users share files, printers, and internet access across many machines.",
        "The internet itself is simply a global network of interconnected smaller networks.",
    ]),
    ("Why Networks Matter", [
        "Networking enables collaboration tools, cloud services, and real-time communication.",
        "Centralizing resources on a network reduces duplicate hardware and software costs.",
        "Modern applications assume constant connectivity, making network design a core skill.",
    ]),
    ("Types of Networks: LAN, MAN, WAN", [
        "A LAN (Local Area Network) covers a small area like a home, office, or campus.",
        "A MAN (Metropolitan Area Network) spans a city, connecting multiple LANs together.",
        "A WAN (Wide Area Network) covers large distances, often crossing countries or continents.",
    ]),
    ("Network Topologies", [
        "A star topology connects every device to a central hub or switch.",
        "A bus topology shares a single communication line among all connected devices.",
        "A mesh topology gives each device multiple redundant paths to every other device.",
    ]),
    # Unit: The OSI and TCP/IP Models
    ("Why Layered Models Exist", [
        "Layered models split networking into independent, swappable pieces of functionality.",
        "Each layer only needs to know how to talk to the layer directly above and below it.",
        "This separation lets vendors build interoperable hardware and software independently.",
    ]),
    ("The Seven OSI Layers", [
        "From bottom to top: Physical, Data Link, Network, Transport, Session, Presentation, Application.",
        "Lower layers move raw bits and frames; upper layers handle formatting and user-facing data.",
        "The OSI model is mostly a teaching and reference tool rather than a literal implementation.",
    ]),
    ("The Four TCP/IP Layers", [
        "The practical internet stack collapses OSI's seven layers into four: Link, Internet, Transport, Application.",
        "TCP/IP is the model actually implemented by real operating systems and routers.",
        "Every packet sent on the internet passes through all four TCP/IP layers on both ends.",
    ]),
    ("Mapping OSI to TCP/IP", [
        "The Internet layer corresponds to OSI's Network layer, both handling addressing and routing.",
        "TCP/IP's Application layer absorbs OSI's Session, Presentation, and Application layers.",
        "Understanding both models helps when reading networking documentation from different eras.",
    ]),
    # Unit: Physical Layer
    ("Transmission Media", [
        "Copper cabling (like Ethernet) transmits data as electrical signals over twisted-pair wires.",
        "Fiber-optic cable transmits data as pulses of light, allowing much higher bandwidth over distance.",
        "Wireless transmission uses radio waves, trading mobility for susceptibility to interference.",
    ]),
    ("Signal Encoding Basics", [
        "Encoding schemes convert binary data into physical signals suitable for the transmission medium.",
        "Digital signaling represents bits as discrete voltage or light levels rather than continuous waves.",
        "Noise and attenuation degrade signals over distance, limiting how far raw data can travel reliably.",
    ]),
    ("Bandwidth vs Throughput vs Latency", [
        "Bandwidth is the theoretical maximum data rate a link can carry, measured in bits per second.",
        "Throughput is the actual achieved data rate, usually lower than bandwidth due to overhead.",
        "Latency is the time delay for data to travel from sender to receiver, independent of bandwidth.",
    ]),
    # Unit: Data Link Layer
    ("Framing and Error Detection", [
        "The data link layer packages bits into frames with defined start and end boundaries.",
        "Checksums like CRC let a receiver detect whether a frame was corrupted in transit.",
        "Detecting an error usually triggers a retransmission request rather than silent data loss.",
    ]),
    ("MAC Addresses and Switching", [
        "Every network interface has a unique MAC address burned in at the hardware level.",
        "A switch reads MAC addresses to forward frames only to the intended destination port.",
        "Switches build a MAC address table by observing which port each address appears on.",
    ]),
    ("CSMA/CD and CSMA/CA", [
        "CSMA/CD detects collisions on shared wired networks and retransmits after a random delay.",
        "CSMA/CA avoids collisions on wireless networks by waiting and signaling intent before sending.",
        "Both protocols coordinate access to a shared medium among multiple competing devices.",
    ]),
    ("VLANs", [
        "A VLAN (Virtual LAN) logically segments one physical network into multiple isolated broadcast domains.",
        "VLANs improve security and reduce unnecessary broadcast traffic between unrelated groups of devices.",
        "Trunk links carry tagged traffic for multiple VLANs over a single physical connection.",
    ]),
    # Unit: Network Layer & Routing
    ("IP Addressing: IPv4 vs IPv6", [
        "IPv4 addresses are 32 bits, written as four decimal octets, offering about 4 billion unique addresses.",
        "IPv6 addresses are 128 bits, designed to solve IPv4 address exhaustion for a growing internet.",
        "Most networks today run IPv4 and IPv6 side by side during a long transition period.",
    ]),
    ("Subnetting Basics", [
        "Subnetting divides a large IP address block into smaller, more manageable sub-networks.",
        "A subnet mask determines which bits of an address identify the network versus the host.",
        "Subnetting reduces broadcast traffic and lets organizations allocate address space efficiently.",
    ]),
    ("Routing Tables and Forwarding", [
        "A router consults its routing table to decide which interface forwards an incoming packet.",
        "Each table entry maps a destination network to a next-hop address and outgoing interface.",
        "Packets are forwarded hop by hop until they reach a router directly connected to the destination.",
    ]),
    ("Distance-Vector vs Link-State Routing", [
        "Distance-vector protocols share their entire routing table with directly connected neighbors.",
        "Link-state protocols share only local link information but flood it to the entire network.",
        "Link-state protocols like OSPF converge faster and scale better than distance-vector ones like RIP.",
    ]),
    # Unit: Transport Layer
    ("Ports and Multiplexing", [
        "Port numbers let a single IP address support many simultaneous network conversations.",
        "The transport layer uses source and destination ports to multiplex data to the right application.",
        "Well-known ports like 80 and 443 are reserved for standard services such as HTTP and HTTPS.",
    ]),
    ("TCP: Connections, Reliability, Flow Control", [
        "TCP establishes a connection using a three-way handshake before any data is exchanged.",
        "Sequence numbers and acknowledgments let TCP detect and retransmit lost segments reliably.",
        "Flow control prevents a fast sender from overwhelming a slower receiver's buffer.",
    ]),
    ("UDP: Connectionless and Low Overhead", [
        "UDP sends data without establishing a connection or guaranteeing delivery order.",
        "Lower overhead makes UDP well suited to real-time applications like video calls and gaming.",
        "Applications using UDP must implement their own reliability logic if they need it.",
    ]),
    ("TCP Congestion Control", [
        "Congestion control adjusts how much data TCP sends based on detected network congestion.",
        "Slow start begins conservatively, doubling the sending rate until congestion is detected.",
        "Detecting packet loss causes TCP to sharply reduce its sending rate to relieve congestion.",
    ]),
    # Unit: Application Layer Protocols
    ("DNS: Name Resolution", [
        "DNS translates human-readable domain names into the IP addresses computers use to route traffic.",
        "A DNS query typically travels from a resolver to root, then top-level domain, then authoritative servers.",
        "Caching DNS results at each step reduces repeated lookups and speeds up future requests.",
    ]),
    ("HTTP and HTTPS", [
        "HTTP is a request-response protocol where a client asks a server for a resource.",
        "HTTP is stateless by design, treating each request independently of prior ones.",
        "HTTPS adds TLS encryption on top of HTTP to protect data from eavesdropping and tampering.",
    ]),
    ("Email: SMTP and Delivery", [
        "SMTP is the protocol used to send email from a client or server to a recipient's mail server.",
        "Mail servers relay messages hop by hop until they reach the recipient's mailbox server.",
        "Retrieval protocols like IMAP, separate from SMTP, are used to read received mail.",
    ]),
    ("FTP and File Transfer", [
        "FTP transfers files between a client and server using separate control and data connections.",
        "Plain FTP sends credentials and data unencrypted, making it unsuitable for sensitive transfers.",
        "Secure alternatives like SFTP wrap file transfer in an encrypted channel.",
    ]),
    ("Putting the Application Layer Together", [
        "Application-layer protocols all rely on the transport layer beneath them for delivery.",
        "Most modern application protocols choose TCP for reliability or UDP for speed, based on need.",
        "Understanding one protocol's request-response pattern makes the others easier to learn.",
    ]),
    # Unit: Network Security Basics
    ("Common Network Threats", [
        "Eavesdropping lets an attacker read unencrypted traffic passing across a network.",
        "Spoofing involves forging a source address to impersonate a trusted device or user.",
        "Denial-of-service attacks flood a target with traffic to exhaust its resources.",
    ]),
    ("Firewalls and Access Control", [
        "A firewall filters traffic based on rules about allowed source, destination, and port.",
        "Access control lists restrict which devices or users may reach specific network resources.",
        "Firewalls can operate at the network perimeter or on individual hosts.",
    ]),
    ("Encryption: Symmetric vs Asymmetric", [
        "Symmetric encryption uses one shared secret key for both encrypting and decrypting data.",
        "Asymmetric encryption uses a public key to encrypt and a private key to decrypt.",
        "Real systems often combine both: asymmetric encryption to exchange a symmetric session key.",
    ]),
    ("VPNs", [
        "A VPN creates an encrypted tunnel between a device and a remote network over the public internet.",
        "VPNs let remote users access internal resources as if they were on the local network.",
        "Tunneling protocols wrap original packets inside new, encrypted packets for transit.",
    ]),
    # Unit: Wireless and Mobile Networks
    ("Wi-Fi Standards and Access Points", [
        "Wi-Fi standards like 802.11ac and 802.11ax define speed, range, and frequency behavior.",
        "An access point bridges wireless clients onto a wired network infrastructure.",
        "Multiple access points with the same network name let devices roam without reconnecting manually.",
    ]),
    ("Cellular Network Generations", [
        "Each cellular generation, from 3G through 5G, has increased data speed and reduced latency.",
        "5G networks use higher frequency bands to achieve greater bandwidth over shorter ranges.",
        "Cellular networks hand off active connections between towers as a device moves.",
    ]),
    ("Mobility Management", [
        "Mobile devices frequently change networks, requiring mechanisms to maintain active sessions.",
        "Mobile IP allows a device to keep a consistent address while roaming across networks.",
        "Handoff procedures minimize interruption when a device switches between access points or towers.",
    ]),
    # Unit: Network Performance and QoS
    ("Latency, Jitter, and Packet Loss", [
        "Latency measures the delay for a packet to travel from source to destination.",
        "Jitter is the variation in latency between consecutive packets in the same stream.",
        "Packet loss occurs when packets fail to arrive, often due to congestion or errors.",
    ]),
    ("Quality of Service Mechanisms", [
        "QoS mechanisms prioritize certain traffic types, such as voice, over less time-sensitive data.",
        "Traffic classification tags packets so network devices can apply consistent prioritization.",
        "Without QoS, all traffic competes equally for bandwidth regardless of its sensitivity to delay.",
    ]),
    ("Congestion and Traffic Shaping", [
        "Congestion occurs when offered traffic exceeds a link's available capacity.",
        "Traffic shaping smooths bursts of traffic to fit within an agreed bandwidth profile.",
        "Buffering absorbs short bursts but excessive buffering can itself introduce added latency.",
    ]),
    # Unit: Summary and Review
    ("Recap: The Protocol Stack", [
        "Data moves down the sender's stack, across the physical medium, then up the receiver's stack.",
        "Each layer adds its own header, and the receiving layer strips the matching header off.",
        "Layers cooperate without needing to know the internal details of layers above or below them.",
    ]),
    ("Key Takeaways", [
        "Reliable delivery, addressing, and routing are solved at different, cooperating layers.",
        "Security and performance are cross-cutting concerns that touch every layer of the stack.",
        "A solid grasp of TCP/IP fundamentals underlies nearly all modern networked systems.",
    ]),
]


def build_deck(path: Path) -> None:
    assert len(SLIDES) == 40, f"expected 40 slides, got {len(SLIDES)}"
    doc = pymupdf.open()
    for title, sentences in SLIDES:
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page.insert_text((72, 72), title, fontsize=22, fontname="helv")
        y = 130
        for sentence in sentences:
            page.insert_text((72, y), sentence, fontsize=13, fontname="helv")
            y += 28
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    doc.close()


def main() -> None:
    build_deck(DECK_PATH)
    print(f"wrote {DECK_PATH} ({len(SLIDES)} slides)")


if __name__ == "__main__":
    main()
