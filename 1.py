import re
def _extract_shortcode(provider_name: str) -> str:
        """
        Extract the shortcode from the provider name.
        
        The shortcode is the second word from the end, before the service provider number.
        Example: "Little Harvard Childcare Ltd. - GL (24KE0503)" -> "GL"
        
        Args:
            provider_name: The full provider name
            
        Returns:
            The extracted shortcode or empty string if not found
        """
        try:
            # Regular expression to match the pattern: something - XX (numbers)
            # where XX is the shortcode
            match = re.search(r'- ([A-Z]+) \(', provider_name)
            if match:
                return match.group(1)
            
            # Alternate method: try to get second word from end (split by spaces)
            parts = provider_name.split()
            if len(parts) >= 3 and "(" in parts[-1]:
                return parts[-2].strip("-()")
            
            # If all fails, return empty string
            return ""
        except Exception as e:
            return ""
        
print(_extract_shortcode('Little Harvard Childcare Ltd-BH   (23KE0483)                             '))