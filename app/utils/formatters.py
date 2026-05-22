def num_to_words(n):
    ones = ['','One','Two','Three','Four','Five','Six','Seven','Eight','Nine',
            'Ten','Eleven','Twelve','Thirteen','Fourteen','Fifteen','Sixteen',
            'Seventeen','Eighteen','Nineteen']
    tens = ['','','Twenty','Thirty','Forty','Fifty','Sixty','Seventy','Eighty','Ninety']
    def say(n):
        if n < 20:   return ones[n]
        if n < 100:  return tens[n//10]+(' '+ones[n%10] if n%10 else '')
        if n < 1000: return ones[n//100]+' Hundred'+((' and '+say(n%100)) if n%100 else '')
        if n < 100000:   return say(n//1000)+' Thousand'+((' '+say(n%1000)) if n%1000 else '')
        if n < 10000000: return say(n//100000)+' Lakh'+((' '+say(n%100000)) if n%100000 else '')
        return say(n//10000000)+' Crore'+((' '+say(n%10000000)) if n%10000000 else '')
    n = int(abs(n))
    return ('Rupees '+say(n)+' Only') if n else 'Rupees Zero Only'
