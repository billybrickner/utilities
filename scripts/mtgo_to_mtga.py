#!/usr/bin/env python

import requests
import xml.etree.ElementTree as ET
import sys

def convert_decklist(decklist):
    converted_list = []
    for card in decklist:
        quantity = card.attrib['Quantity']
        card_name = card.attrib['Name']

        # Convert card name to MTGA format using Scryfall API
        scryfall_query = convert_card_name(card_name)
        if scryfall_query:
            set_name, mtga_id = scryfall_query
            converted_line = f"{quantity} {card_name} ({set_name.upper()}) {mtga_id}"
            converted_list.append(converted_line)

    return converted_list

def convert_card_name(card_name):
    # Query Scryfall API to get MTGA card name
    response = requests.get(f"https://api.scryfall.com/cards/named?fuzzy={card_name}")
    if response.status_code == 200:
        data = response.json()
        if 'arena_id' in data:
            return data['set'], data['arena_id']

    # If the card is not found in MTGA, return None
    return None

if __name__ == '__main__':
    # Check if deck name is provided as an argument
    if len(sys.argv) < 2:
        print("Please provide the deck name as an argument.")
        sys.exit(1)

    deck_name = sys.argv[1]
    deck_file = f"{deck_name}.dek"

    try:
        # Parse MTGO .dek file
        tree = ET.parse(deck_file)
        root = tree.getroot()
        cards = root.findall(".//Cards")

        # Convert MTGO decklist to MTGA format
        mtga_decklist = convert_decklist(cards)

        # Save MTGA decklist to file
        output_file = f"{deck_name}_mtga.txt"
        with open(output_file, 'w') as file:
            file.write('\n'.join(mtga_decklist))

        print(f"MTGA decklist created: {output_file}")

    except FileNotFoundError:
        print(f"Deck file '{deck_file}' not found.")

